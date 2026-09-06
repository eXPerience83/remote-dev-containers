// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Remote Dev contributors

#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/landlock.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

#ifndef O_PATH
#define O_PATH 010000000
#endif

#define REMOTE_DEV_MIN_LANDLOCK_ABI 3
#define REMOTE_DEV_MAX_WRITE_PATHS 32

static void usage(FILE *stream) {
    fprintf(stream,
            "Usage:\n"
            "  remote-dev-project-write-guard --probe\n"
            "  remote-dev-project-write-guard --workspace PATH --project PATH "
            "--write PATH [--write PATH ...] -- COMMAND [ARG ...]\n");
}

static int query_landlock_abi(void) {
    long result = syscall(SYS_landlock_create_ruleset, NULL, 0,
                          LANDLOCK_CREATE_RULESET_VERSION);
    if (result < 0) {
        return -errno;
    }
    if (result > INT_MAX) {
        return -EOVERFLOW;
    }
    return (int)result;
}

static uint64_t handled_write_access(void) {
    return LANDLOCK_ACCESS_FS_WRITE_FILE |
           LANDLOCK_ACCESS_FS_REMOVE_DIR |
           LANDLOCK_ACCESS_FS_REMOVE_FILE |
           LANDLOCK_ACCESS_FS_MAKE_CHAR |
           LANDLOCK_ACCESS_FS_MAKE_DIR |
           LANDLOCK_ACCESS_FS_MAKE_REG |
           LANDLOCK_ACCESS_FS_MAKE_SOCK |
           LANDLOCK_ACCESS_FS_MAKE_FIFO |
           LANDLOCK_ACCESS_FS_MAKE_BLOCK |
           LANDLOCK_ACCESS_FS_MAKE_SYM |
           LANDLOCK_ACCESS_FS_REFER |
           LANDLOCK_ACCESS_FS_TRUNCATE;
}

static bool is_path_prefix(const char *parent, const char *child) {
    size_t parent_len = strlen(parent);

    if (strcmp(parent, child) == 0) {
        return true;
    }
    if (parent_len == 0 || strncmp(parent, child, parent_len) != 0) {
        return false;
    }
    return parent[parent_len - 1] == '/' || child[parent_len] == '/';
}

static int reject_symlink_components(const char *path) {
    char current[PATH_MAX];
    size_t path_len = strlen(path);
    size_t current_len = 0;

    if (path_len == 0 || path[0] != '/' || path_len >= sizeof(current)) {
        return -EINVAL;
    }

    current[0] = '/';
    current[1] = '\0';
    current_len = 1;

    const char *cursor = path + 1;
    while (*cursor != '\0') {
        while (*cursor == '/') {
            ++cursor;
        }
        if (*cursor == '\0') {
            break;
        }

        const char *end = cursor;
        while (*end != '\0' && *end != '/') {
            ++end;
        }
        size_t component_len = (size_t)(end - cursor);
        if (component_len == 0 ||
            current_len + component_len + 2 > sizeof(current)) {
            return -EINVAL;
        }

        if (current_len > 1) {
            current[current_len++] = '/';
        }
        memcpy(current + current_len, cursor, component_len);
        current_len += component_len;
        current[current_len] = '\0';

        struct stat info;
        if (lstat(current, &info) != 0) {
            return -errno;
        }
        if (S_ISLNK(info.st_mode)) {
            return -ELOOP;
        }
        cursor = end;
    }

    return 0;
}

static int canonical_directory(const char *input, char output[PATH_MAX]) {
    struct stat info;
    int component_result = reject_symlink_components(input);

    if (component_result != 0) {
        return component_result;
    }
    if (realpath(input, output) == NULL) {
        return -errno;
    }
    if (lstat(output, &info) != 0) {
        return -errno;
    }
    if (!S_ISDIR(info.st_mode) || S_ISLNK(info.st_mode)) {
        return -ENOTDIR;
    }
    return 0;
}

static bool is_direct_child(const char *workspace, const char *project) {
    size_t workspace_len = strlen(workspace);

    if (strcmp(workspace, "/") == 0 ||
        strncmp(workspace, project, workspace_len) != 0 ||
        project[workspace_len] != '/') {
        return false;
    }

    const char *name = project + workspace_len + 1;
    return *name != '\0' && strchr(name, '/') == NULL;
}

static int add_write_rule(int ruleset_fd, const char *path, uint64_t access) {
    int parent_fd = open(path, O_PATH | O_CLOEXEC | O_DIRECTORY | O_NOFOLLOW);
    if (parent_fd < 0) {
        return -errno;
    }

    struct landlock_path_beneath_attr rule = {
        .allowed_access = access,
        .parent_fd = parent_fd,
    };
    int result = 0;
    if (syscall(SYS_landlock_add_rule, ruleset_fd, LANDLOCK_RULE_PATH_BENEATH,
                &rule, 0) != 0) {
        result = -errno;
    }
    close(parent_fd);
    return result;
}

static void print_errno_message(const char *prefix, int negative_errno) {
    int error = negative_errno < 0 ? -negative_errno : negative_errno;
    fprintf(stderr, "ERROR: %s: %s\n", prefix, strerror(error));
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--probe") == 0) {
        int abi = query_landlock_abi();
        if (abi < 0) {
            print_errno_message("Landlock is unavailable", abi);
            return 2;
        }
        if (abi < REMOTE_DEV_MIN_LANDLOCK_ABI) {
            fprintf(stderr,
                    "ERROR: Landlock ABI %d is too old; Remote Dev requires ABI %d or newer\n",
                    abi, REMOTE_DEV_MIN_LANDLOCK_ABI);
            return 2;
        }
        printf("Landlock ABI: %d\n", abi);
        return 0;
    }

    const char *workspace_arg = NULL;
    const char *project_arg = NULL;
    const char *write_args[REMOTE_DEV_MAX_WRITE_PATHS];
    size_t write_count = 0;
    int command_index = -1;

    for (int index = 1; index < argc; ++index) {
        if (strcmp(argv[index], "--") == 0) {
            command_index = index + 1;
            break;
        }
        if (strcmp(argv[index], "--workspace") == 0) {
            if (++index >= argc || workspace_arg != NULL) {
                usage(stderr);
                return 2;
            }
            workspace_arg = argv[index];
            continue;
        }
        if (strcmp(argv[index], "--project") == 0) {
            if (++index >= argc || project_arg != NULL) {
                usage(stderr);
                return 2;
            }
            project_arg = argv[index];
            continue;
        }
        if (strcmp(argv[index], "--write") == 0) {
            if (++index >= argc || write_count >= REMOTE_DEV_MAX_WRITE_PATHS) {
                usage(stderr);
                return 2;
            }
            write_args[write_count++] = argv[index];
            continue;
        }

        usage(stderr);
        return 2;
    }

    if (workspace_arg == NULL || project_arg == NULL || write_count == 0 ||
        command_index < 0 || command_index >= argc) {
        usage(stderr);
        return 2;
    }

    int abi = query_landlock_abi();
    if (abi < 0) {
        print_errno_message("Landlock is unavailable; managed agent launch is blocked", abi);
        return 2;
    }
    if (abi < REMOTE_DEV_MIN_LANDLOCK_ABI) {
        fprintf(stderr,
                "ERROR: Landlock ABI %d cannot enforce the managed project write boundary; ABI %d or newer is required\n",
                abi, REMOTE_DEV_MIN_LANDLOCK_ABI);
        return 2;
    }

    char workspace[PATH_MAX];
    char project[PATH_MAX];
    int path_result = canonical_directory(workspace_arg, workspace);
    if (path_result != 0) {
        print_errno_message("workspace path is unavailable or unsafe", path_result);
        return 2;
    }
    path_result = canonical_directory(project_arg, project);
    if (path_result != 0) {
        print_errno_message("project path is unavailable or unsafe", path_result);
        return 2;
    }
    if (!is_direct_child(workspace, project)) {
        fprintf(stderr,
                "ERROR: managed project must be one physical direct child of the workspace collection\n");
        return 2;
    }

    char scratch[PATH_MAX];
    if (snprintf(scratch, sizeof(scratch), "%s/.remote-dev-tmp", workspace) >=
        (int)sizeof(scratch)) {
        fprintf(stderr, "ERROR: workspace path is too long\n");
        return 2;
    }

    char canonical_writes[REMOTE_DEV_MAX_WRITE_PATHS][PATH_MAX];
    bool project_is_writable = false;
    for (size_t index = 0; index < write_count; ++index) {
        path_result = canonical_directory(write_args[index], canonical_writes[index]);
        if (path_result != 0) {
            print_errno_message("managed writable path is unavailable or unsafe", path_result);
            return 2;
        }

        const char *candidate = canonical_writes[index];
        if (strcmp(candidate, workspace) == 0) {
            fprintf(stderr,
                    "ERROR: the workspace collection root can never be a managed writable path\n");
            return 2;
        }
        if (is_path_prefix(workspace, candidate) &&
            !is_path_prefix(project, candidate) &&
            !is_path_prefix(scratch, candidate)) {
            fprintf(stderr,
                    "ERROR: managed writable path escapes the selected project inside the workspace collection\n");
            return 2;
        }
        if (strcmp(candidate, project) == 0) {
            project_is_writable = true;
        }
    }
    if (!project_is_writable) {
        fprintf(stderr,
                "ERROR: managed project write boundary does not include the selected project\n");
        return 2;
    }

    const uint64_t handled_access = handled_write_access();
    struct landlock_ruleset_attr ruleset = {
        .handled_access_fs = handled_access,
    };

    int ruleset_fd = (int)syscall(SYS_landlock_create_ruleset, &ruleset,
                                  sizeof(ruleset.handled_access_fs), 0);
    if (ruleset_fd < 0) {
        print_errno_message("failed to create Landlock project write ruleset", -errno);
        return 2;
    }

    for (size_t index = 0; index < write_count; ++index) {
        int rule_result = add_write_rule(ruleset_fd, canonical_writes[index],
                                         handled_access);
        if (rule_result != 0) {
            close(ruleset_fd);
            print_errno_message("failed to add managed writable path", rule_result);
            return 2;
        }
    }

    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0) {
        int saved_errno = errno;
        close(ruleset_fd);
        print_errno_message("failed to set no_new_privs before Landlock", -saved_errno);
        return 2;
    }
    if (syscall(SYS_landlock_restrict_self, ruleset_fd, 0) != 0) {
        int saved_errno = errno;
        close(ruleset_fd);
        print_errno_message("failed to enforce Landlock project write boundary", -saved_errno);
        return 2;
    }
    close(ruleset_fd);

    execvp(argv[command_index], &argv[command_index]);
    print_errno_message("managed agent executable could not be started", -errno);
    return 126;
}
