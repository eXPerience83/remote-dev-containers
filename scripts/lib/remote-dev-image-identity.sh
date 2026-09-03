#!/usr/bin/env bash

remote_dev_validate_image_identity() {
  local channel="$1"
  local version="$2"
  local source_revision="$3"
  local expected_short=""

  case "$channel" in
    local)
      if [[ -z "$version" || "$version" == unknown || "$version" == unavailable ]]; then
        echo "ERROR: local image version metadata is unavailable" >&2
        return 1
      fi
      if [[ -z "$source_revision" || "$source_revision" == unknown || "$source_revision" == unavailable ]]; then
        echo "ERROR: local source revision metadata is unavailable" >&2
        return 1
      fi
      ;;
    dev)
      if [[ ! "$version" =~ ^candidate-pr-[1-9][0-9]*$ ]]; then
        echo "ERROR: dev image version must use candidate-pr-<PR>; got $version" >&2
        return 1
      fi
      if [[ ! "$source_revision" =~ ^[0-9a-f]{40}$ ]]; then
        echo "ERROR: dev source revision must be a lowercase 40-character Git SHA" >&2
        return 1
      fi
      ;;
    edge)
      if [[ ! "$version" =~ ^edge-[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9a-f]{7}$ ]]; then
        echo "ERROR: edge image version must use edge-YYYY.MM.DD-<7-char-sha>; got $version" >&2
        return 1
      fi
      if [[ ! "$source_revision" =~ ^[0-9a-f]{40}$ ]]; then
        echo "ERROR: edge source revision must be a lowercase 40-character Git SHA" >&2
        return 1
      fi
      expected_short="${source_revision:0:7}"
      if [[ "${version##*-}" != "$expected_short" ]]; then
        echo "ERROR: edge image version short SHA does not match the embedded source revision" >&2
        return 1
      fi
      ;;
    stable)
      if [[ ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "ERROR: stable image version must use vMAJOR.MINOR.PATCH; got $version" >&2
        return 1
      fi
      if [[ ! "$source_revision" =~ ^[0-9a-f]{40}$ ]]; then
        echo "ERROR: stable source revision must be a lowercase 40-character Git SHA" >&2
        return 1
      fi
      ;;
    *)
      echo "ERROR: image channel must be one of local, dev, edge or stable; got $channel" >&2
      return 1
      ;;
  esac
}
