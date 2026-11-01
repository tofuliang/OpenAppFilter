(function(window) {
    'use strict';

    function decodeHashPart(value) {
        try {
            return decodeURIComponent(value.replace(/\+/g, ' '));
        } catch (error) {
            return null;
        }
    }

    function hashPartName(part) {
        var separator = part.indexOf('=');
        return decodeHashPart(separator < 0 ? part : part.slice(0, separator));
    }

    function create(options) {
        var ids = options.ids;
        var currentId = null;
        var initialized = false;
        var defaultId = isValid(options.defaultId) ? options.defaultId : ids[0];

        function isValid(id) {
            return typeof id === 'string' && ids.indexOf(id) !== -1;
        }

        function readStoredId() {
            try {
                var id = window.localStorage.getItem(options.storageKey);
                return isValid(id) ? id : null;
            } catch (error) {
                return null;
            }
        }

        function storeId(id) {
            try {
                window.localStorage.setItem(options.storageKey, id);
            } catch (error) {
                // Tab navigation must still work when storage is unavailable.
            }
        }

        function readHashId() {
            var parts = window.location.hash.slice(1).split('&');
            for (var i = 0; i < parts.length; i++) {
                if (hashPartName(parts[i]) === 'tab') {
                    var separator = parts[i].indexOf('=');
                    return separator < 0 ? null : decodeHashPart(parts[i].slice(separator + 1));
                }
            }
            return null;
        }

        function writeHash(id, replace) {
            var hash = window.location.hash.slice(1);
            var parts = hash ? hash.split('&') : [];
            var nextParts = [];
            var tabPart = 'tab=' + encodeURIComponent(id);
            var written = false;

            for (var i = 0; i < parts.length; i++) {
                if (hashPartName(parts[i]) !== 'tab') {
                    nextParts.push(parts[i]);
                } else if (!written) {
                    nextParts.push(tabPart);
                    written = true;
                }
            }
            if (!written) {
                nextParts.push(tabPart);
            }

            var nextHash = '#' + nextParts.join('&');
            if (window.location.hash !== nextHash) {
                window.history[replace ? 'replaceState' : 'pushState'](
                    window.history.state,
                    '',
                    window.location.pathname + window.location.search + nextHash
                );
            }
        }

        function initial(preferredId) {
            var hashId = readHashId();
            var id = isValid(hashId) ? hashId :
                (isValid(preferredId) ? preferredId : (readStoredId() || defaultId));
            currentId = id;
            initialized = true;
            storeId(id);
            writeHash(id, true);
            return id;
        }

        function select(id) {
            if (!isValid(id)) {
                return;
            }
            currentId = id;
            storeId(id);
            writeHash(id, false);
        }

        function navigate() {
            if (!initialized) {
                return;
            }
            var hashId = readHashId();
            var id = isValid(hashId) ? hashId : (readStoredId() || defaultId);
            storeId(id);
            writeHash(id, true);
            if (id !== currentId) {
                currentId = id;
                if (typeof options.onNavigate === 'function') {
                    options.onNavigate(id);
                }
            }
        }

        window.addEventListener('hashchange', navigate);
        window.addEventListener('popstate', navigate);

        return {initial: initial, select: select};
    }

    window.OAFTabState = {create: create};
})(window);
