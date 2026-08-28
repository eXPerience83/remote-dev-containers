(() => {
  'use strict';

  const INSTALL_MARK = Symbol.for('io.github.experience83.remote-dev.osc52-write');
  const MAX_RAW_BYTES = 100000;
  const MAX_BASE64_CHARS = 4 * Math.ceil(MAX_RAW_BYTES / 3);
  const CANONICAL_BASE64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;

  const install = term => {
    if (!term || term[INSTALL_MARK] || !term.parser ||
        typeof term.parser.registerOscHandler !== 'function') {
      return;
    }

    const registration = term.parser.registerOscHandler(52, data => {
      let bytes = null;
      let text = null;
      let textarea = null;

      try {
        const separator = data.indexOf(';');
        if (separator < 0) return true;

        const selector = data.slice(0, separator);
        const encoded = data.slice(separator + 1);
        if (selector !== '' && selector !== 'c') return true;
        if (encoded === '?') return true;
        if (encoded.length === 0 || encoded.length > MAX_BASE64_CHARS ||
            encoded.length % 4 !== 0 || !CANONICAL_BASE64.test(encoded)) {
          return true;
        }

        const binary = atob(encoded);
        if (btoa(binary) !== encoded) return true;
        if (binary.length > MAX_RAW_BYTES) return true;

        bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) {
          bytes[index] = binary.charCodeAt(index);
        }
        text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);

        textarea = document.createElement('textarea');
        textarea.readOnly = true;
        textarea.tabIndex = -1;
        textarea.setAttribute('aria-hidden', 'true');
        textarea.style.cssText =
          'position:fixed;left:-10000px;top:0;width:1px;height:1px;overflow:hidden;';
        textarea.value = text;
        document.body.appendChild(textarea);
        textarea.focus({ preventScroll: true });
        textarea.select();
        textarea.setSelectionRange(0, textarea.value.length);
        const copySucceeded = document.execCommand('copy') === true;
        if (!copySucceeded) return true;
        return true;
      } catch (_) {
        return true;
      } finally {
        if (textarea) {
          textarea.value = '';
          textarea.remove();
        }
        if (bytes) bytes.fill(0);
        text = null;
        try {
          term.focus();
        } catch (_) {}
      }
    });

    Object.defineProperty(term, INSTALL_MARK, {
      configurable: false,
      enumerable: false,
      value: registration,
      writable: false,
    });
  };

  if (window.term) {
    try {
      install(window.term);
    } catch (_) {}
    return;
  }

  Object.defineProperty(window, 'term', {
    configurable: true,
    enumerable: true,
    get() {
      return undefined;
    },
    set(term) {
      delete window.term;
      window.term = term;
      try {
        install(term);
      } catch (_) {}
    },
  });
})();
