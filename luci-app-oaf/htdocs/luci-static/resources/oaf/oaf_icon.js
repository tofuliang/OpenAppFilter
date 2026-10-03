(function(window, $) {
    'use strict';

    var iconColors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#f97316', '#ec4899', '#84cc16', '#6366f1'];
    var iconStatusCache = {};

    function hashColor(value) {
        var text = value ? String(value) : '';
        var hash = 0;

        if (!text) {
            return iconColors[0];
        }

        for (var i = 0; i < text.length; i++) {
            hash = text.charCodeAt(i) + ((hash << 5) - hash);
        }

        return iconColors[Math.abs(hash) % iconColors.length];
    }

    function firstLetter(value) {
        var text = value ? String(value).trim() : '';
        return text ? text.charAt(0).toUpperCase() : '?';
    }

    function appIconSrc(resourceBase, appId) {
        var id = appId === undefined || appId === null ? '' : String(appId).trim();
        return id ? resourceBase + '/oaf/app_icons/' + encodeURIComponent(id) + '.png' : '';
    }

    function createLetterIcon(name, options) {
        options = options || {};
        return $('<span>')
            .addClass(options.className || 'oaf-generated-app-icon')
            .css({
                width: options.size || '20px',
                height: options.size || '20px',
                borderRadius: options.radius || '5px',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: hashColor(name),
                color: '#fff',
                fontSize: options.fontSize || '11px',
                fontWeight: '700',
                flexShrink: 0,
                lineHeight: 1
            })
            .text(firstLetter(name));
    }

    function createAppIcon(appId, name, resourceBase, options) {
        options = options || {};
        var appName = name || '';
        var id = appId === undefined || appId === null ? '' : String(appId).trim();
        var src = appIconSrc(resourceBase, id);
        var iconDisabled = options.icon === 0 || options.icon === '0' || options.hasIcon === false;
        var $icon;

        if (id && iconDisabled) {
            iconStatusCache[id] = 'failed';
        }

        if (id && !iconDisabled && iconStatusCache[id] === 'loaded') {
            return $('<img>')
                .attr({ src: src, alt: appName })
                .css({
                    width: options.size || '20px',
                    height: options.size || '20px',
                    borderRadius: options.radius || '5px',
                    objectFit: options.objectFit || 'cover',
                    display: 'block',
                    flexShrink: 0
                });
        }

        $icon = createLetterIcon(appName, options);
        if (id && !iconDisabled && iconStatusCache[id] !== 'failed') {
            var loader = new Image();
            loader.onload = function() {
                iconStatusCache[id] = 'loaded';
                $icon.replaceWith($('<img>')
                    .attr({ src: src, alt: appName })
                    .css({
                        width: options.size || '20px',
                        height: options.size || '20px',
                        borderRadius: options.radius || '5px',
                        objectFit: options.objectFit || 'cover',
                        display: 'block',
                        flexShrink: 0,
                        border: 'none',
                        boxShadow: 'none'
                    }));
            };
            loader.onerror = function() {
                iconStatusCache[id] = 'failed';
            };
            loader.src = src;
        }

        return $icon;
    }

    var featureDetailCache = Object.create(null);
    var activeFeatureTrigger = null;
    var featureHideTimer = null;
    var featurePopover = null;

    var defaultFeatureTexts = {
        loading: 'Loading...',
        error: 'Load failed',
        empty: 'No feature rules',
        titleSuffix: 'Feature Rules'
    };

    function normalizeFeatureAppId(value) {
        if (value === undefined || value === null) {
            return '';
        }

        var text = String(value).trim();
        var number = Number(text);
        if (!text || !isFinite(number) || Math.floor(number) !== number || number <= 0) {
            return '';
        }

        return String(number);
    }

    function featureTexts(config) {
        var texts = config && config.texts ? config.texts : {};
        return {
            loading: texts.loading || config.loadingText || defaultFeatureTexts.loading,
            error: texts.error || config.errorText || defaultFeatureTexts.error,
            empty: texts.empty || config.emptyText || defaultFeatureTexts.empty,
            titleSuffix: texts.titleSuffix || config.titleSuffix || defaultFeatureTexts.titleSuffix
        };
    }

    function ensureFeaturePopover() {
        if (featurePopover && document.documentElement.contains(featurePopover)) {
            return featurePopover;
        }

        featurePopover = document.createElement('div');
        featurePopover.id = 'oaf-feature-detail-popover';
        featurePopover.setAttribute('role', 'tooltip');
        featurePopover.setAttribute('aria-hidden', 'true');
        featurePopover.className = 'oaf-feature-detail-popover';
        if (document.body) {
            document.body.appendChild(featurePopover);
        }
        ensureFeaturePopoverStyle();
        return featurePopover;
    }

    function ensureFeaturePopoverStyle() {
        if (document.getElementById('oaf-feature-detail-style')) {
            return;
        }

        var style = document.createElement('style');
        style.id = 'oaf-feature-detail-style';
        style.type = 'text/css';
        style.appendChild(document.createTextNode(
            '.oaf-feature-detail-popover{' +
                'display:none;position:fixed;z-index:10000;box-sizing:border-box;width:max-content;' +
                'max-width:calc(100vw - 16px);max-height:calc(100vh - 16px);overflow:auto;' +
                'padding:10px 12px;border:1px solid var(--border-color-medium,#d1d5db);' +
                'border-radius:6px;background:var(--background-color-high,#fff);' +
                'color:var(--text-color-high,#333);box-shadow:0 8px 24px rgba(0,0,0,.18);' +
                'font-size:13px;line-height:1.45;pointer-events:auto;}' +
            '.oaf-feature-detail-popover.show{display:block;}' +
            '.oaf-feature-detail-title{font-weight:600;margin-bottom:6px;overflow-wrap:anywhere;' +
                'word-break:break-word;}' +
            '.oaf-feature-detail-empty{color:var(--text-color-medium,#6b7280);overflow-wrap:anywhere;' +
                'word-break:break-word;}' +
            '.oaf-feature-detail-rule{padding:6px 0;border-top:1px solid var(--border-color-low,#e5e7eb);' +
                'white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;' +
                'font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono",' +
                '"Courier New",monospace;}' +
            '.oaf-feature-detail-rule:first-of-type{border-top:0;padding-top:0;}' +
            '[data-darkmode="true"] .oaf-feature-detail-popover{' +
                'box-shadow:0 8px 24px rgba(0,0,0,.48);}'
        ));
        (document.head || document.documentElement).appendChild(style);
    }

    function featureTriggerVisible(trigger) {
        return !!(trigger && document.documentElement.contains(trigger) &&
            $(trigger).is(':visible') && $(trigger).css('visibility') !== 'hidden');
    }

    function featureTriggerAppId(trigger) {
        return normalizeFeatureAppId($(trigger).attr('data-oaf-feature-appid'));
    }

    function featurePopoverContains(target) {
        return !!(featurePopover && target &&
            (target === featurePopover || featurePopover.contains(target)));
    }

    function featureTriggerHasFocus(trigger) {
        return !!(trigger && (document.activeElement === trigger || trigger.contains(document.activeElement)));
    }

    function renderFeaturePopover(trigger, entry) {
        var popover = ensureFeaturePopover();
        var $popover = $(popover).empty();
        var name = $(trigger).attr('data-oaf-feature-name') || '';
        var texts = $(trigger).data('oafFeatureTexts') || defaultFeatureTexts;
        var title = name ? name + ' - ' + texts.titleSuffix : texts.titleSuffix;

        $popover.append($('<div>').addClass('oaf-feature-detail-title').text(title));
        if (!entry || entry.state === 'loading' || entry.state === 'idle') {
            $popover.append($('<div>').addClass('oaf-feature-detail-empty').text(texts.loading));
        } else if (entry.state !== 'loaded') {
            $popover.append($('<div>').addClass('oaf-feature-detail-empty').text(texts.error));
        } else if (!Array.isArray(entry.features) || entry.features.length === 0) {
            $popover.append($('<div>').addClass('oaf-feature-detail-empty').text(texts.empty));
        } else {
            entry.features.forEach(function(rule) {
                $popover.append($('<div>').addClass('oaf-feature-detail-rule')
                    .text(rule === undefined || rule === null ? '' : String(rule)));
            });
        }

        $popover.attr('aria-busy', entry && entry.state === 'loading' ? 'true' : 'false');
        return popover;
    }

    function positionFeaturePopover() {
        if (!activeFeatureTrigger || !featureTriggerVisible(activeFeatureTrigger)) {
            if (activeFeatureTrigger) {
                hideFeaturePopover();
            }
            return;
        }

        var popover = ensureFeaturePopover();
        var viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
        var viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
        var padding = 8;
        var availableWidth = Math.max(0, viewportWidth - padding * 2);
        var availableHeight = Math.max(0, viewportHeight - padding * 2);

        popover.style.maxWidth = availableWidth + 'px';
        popover.style.maxHeight = availableHeight + 'px';
        popover.style.left = '-9999px';
        popover.style.top = '-9999px';
        popover.classList.add('show');

        var triggerRect = activeFeatureTrigger.getBoundingClientRect();
        var popoverRect = popover.getBoundingClientRect();
        var width = Math.min(popoverRect.width, availableWidth);
        var height = Math.min(popoverRect.height, availableHeight);
        var left = triggerRect.left + (triggerRect.width - width) / 2;
        var top = triggerRect.top - height - padding;

        if (top < padding) {
            top = triggerRect.bottom + padding;
        }
        left = Math.max(padding, Math.min(left, viewportWidth - width - padding));
        top = Math.max(padding, Math.min(top, viewportHeight - height - padding));

        popover.style.left = Math.round(left) + 'px';
        popover.style.top = Math.round(top) + 'px';
    }

    function featureEntry(appId) {
        var entry = featureDetailCache[appId];
        if (!entry) {
            entry = {state: 'idle', features: [], requesting: false};
            featureDetailCache[appId] = entry;
        }
        return entry;
    }

    function requestFeatureDetail(trigger, appId) {
        var entry = featureEntry(appId);
        var apiUrl = $(trigger).attr('data-oaf-feature-api') || '';

        if (entry.state !== 'idle' || entry.requesting) {
            return entry;
        }

        if (!apiUrl) {
            entry.state = 'error';
            return entry;
        }

        entry.state = 'loading';
        entry.features = [];
        entry.requesting = true;
        $.ajax({
            url: apiUrl,
            type: 'GET',
            dataType: 'json',
            data: {appid: Number(appId)},
            timeout: 10000
        }).done(function(resp) {
            if (resp && resp.code === 2000 && resp.data && Array.isArray(resp.data.features)) {
                entry.state = 'loaded';
                entry.features = resp.data.features.slice();
            } else {
                entry.state = 'error';
                entry.features = [];
            }
            if (activeFeatureTrigger && featureTriggerVisible(activeFeatureTrigger) &&
                featureTriggerAppId(activeFeatureTrigger) === appId) {
                renderFeaturePopover(activeFeatureTrigger, entry);
                positionFeaturePopover();
            }
        }).fail(function() {
            entry.state = 'error';
            entry.features = [];
            if (activeFeatureTrigger && featureTriggerVisible(activeFeatureTrigger) &&
                featureTriggerAppId(activeFeatureTrigger) === appId) {
                renderFeaturePopover(activeFeatureTrigger, entry);
                positionFeaturePopover();
            }
        }).always(function() {
            entry.requesting = false;
        });

        return entry;
    }

    function showFeaturePopover(trigger) {
        if (!featureTriggerVisible(trigger)) {
            hideFeaturePopover();
            return;
        }

        var appId = featureTriggerAppId(trigger);
        if (!appId) {
            hideFeaturePopover();
            return;
        }

        if (featureHideTimer) {
            clearTimeout(featureHideTimer);
            featureHideTimer = null;
        }
        if (activeFeatureTrigger && activeFeatureTrigger !== trigger) {
            $(activeFeatureTrigger).attr('aria-expanded', 'false').removeAttr('aria-describedby');
        }

        activeFeatureTrigger = trigger;
        var entry = featureEntry(appId);
        if (entry.state === 'idle') {
            entry = requestFeatureDetail(trigger, appId);
        }

        renderFeaturePopover(trigger, entry);
        var popover = ensureFeaturePopover();
        $(trigger).attr({'aria-expanded': 'true', 'aria-describedby': popover.id});
        popover.classList.add('show');
        popover.setAttribute('aria-hidden', 'false');
        positionFeaturePopover();
    }

    function hideFeaturePopover() {
        if (featureHideTimer) {
            clearTimeout(featureHideTimer);
            featureHideTimer = null;
        }
        if (activeFeatureTrigger) {
            $(activeFeatureTrigger).attr('aria-expanded', 'false').removeAttr('aria-describedby');
        }
        activeFeatureTrigger = null;
        if (featurePopover) {
            featurePopover.classList.remove('show');
            featurePopover.setAttribute('aria-hidden', 'true');
        }
    }

    function scheduleHideFeaturePopover(trigger) {
        if (featureHideTimer) {
            clearTimeout(featureHideTimer);
        }
        featureHideTimer = setTimeout(function() {
            featureHideTimer = null;
            if (activeFeatureTrigger !== trigger || featureTriggerHasFocus(trigger) ||
                $(trigger).is(':hover') || $(featurePopover).is(':hover')) {
                return;
            }
            hideFeaturePopover();
        }, 150);
    }

    function bindFeatureHover(target, appId, appName, apiUrl, options) {
        var config;
        if (appId && typeof appId === 'object' && !appId.nodeType && !appId.jquery) {
            config = appId;
            appId = config.appid !== undefined ? config.appid : config.appId;
            appName = config.appName !== undefined ? config.appName : config.name;
            apiUrl = config.apiUrl !== undefined ? config.apiUrl : config.url;
        } else {
            config = options || {};
        }

        var id = normalizeFeatureAppId(appId);
        var $target = target && target.jquery ? target : $(target);
        if (!$target || !$target.length) {
            return $target;
        }
        if (!id) {
            return $target;
        }

        var texts = featureTexts(config);
        $target.each(function() {
            var $element = $(this);
            var tagName = (this.tagName || '').toLowerCase();
            if (this.getAttribute('tabindex') === null &&
                !/^(a|button|input|select|textarea|summary)$/.test(tagName)) {
                $element.attr('tabindex', '0');
            }
            $element.addClass('oaf-feature-hover-trigger').attr({
                'data-oaf-feature-appid': id,
                'data-oaf-feature-name': appName === undefined || appName === null ? '' : String(appName),
                'data-oaf-feature-api': apiUrl || '',
                'aria-haspopup': 'true',
                'aria-expanded': 'false'
            }).data('oafFeatureTexts', texts);
            if (!$element.attr('aria-label') && appName) {
                $element.attr('aria-label', String(appName));
            }
        });

        return $target;
    }

    function bindFeatureHoverEvents() {
        if (!$ || !document) {
            return;
        }

        $(document).off('.oafFeatureHover');
        $(document).on('mouseenter.oafFeatureHover', '.oaf-feature-hover-trigger', function() {
            showFeaturePopover(this);
        });
        $(document).on('mouseleave.oafFeatureHover', '.oaf-feature-hover-trigger', function() {
            scheduleHideFeaturePopover(this);
        });
        $(document).on('focusin.oafFeatureHover', '.oaf-feature-hover-trigger', function() {
            showFeaturePopover(this);
        });
        $(document).on('focusout.oafFeatureHover', '.oaf-feature-hover-trigger', function(event) {
            var related = event.relatedTarget;
            if (related && (this.contains(related) || featurePopoverContains(related))) {
                return;
            }
            scheduleHideFeaturePopover(this);
        });
        $(document).on('click.oafFeatureHover', '.oaf-feature-hover-trigger', function() {
            showFeaturePopover(this);
        });
        $(document).on('keydown.oafFeatureHover', '.oaf-feature-hover-trigger', function(event) {
            if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
                event.preventDefault();
                showFeaturePopover(this);
            }
        });
        $(document).on('mouseenter.oafFeatureHover', '.oaf-feature-detail-popover', function() {
            if (featureHideTimer) {
                clearTimeout(featureHideTimer);
                featureHideTimer = null;
            }
        });
        $(document).on('mouseleave.oafFeatureHover', '.oaf-feature-detail-popover', function() {
            if (activeFeatureTrigger) {
                scheduleHideFeaturePopover(activeFeatureTrigger);
            }
        });
        $(document).on('mousedown.oafFeatureHover', function(event) {
            if (!$(event.target).closest('.oaf-feature-hover-trigger, .oaf-feature-detail-popover').length) {
                hideFeaturePopover();
            }
        });
        $(document).on('keydown.oafFeatureHover', function(event) {
            if (event.key === 'Escape' && activeFeatureTrigger) {
                hideFeaturePopover();
            }
        });
        $(window).on('resize.oafFeatureHover scroll.oafFeatureHover', function() {
            if (activeFeatureTrigger) {
                positionFeaturePopover();
            }
        });
    }

    window.OAFIcon = {
        colors: iconColors,
        hashColor: hashColor,
        appIconSrc: appIconSrc,
        createLetterIcon: createLetterIcon,
        createAppIcon: createAppIcon,
        bindFeatureHover: bindFeatureHover,
        hideFeatureHover: hideFeaturePopover
    };
    bindFeatureHoverEvents();
 })(window, window.jQuery);
