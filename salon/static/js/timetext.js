// polyfill, see https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Date/now
if (!Date.now) {
    Date.now = function now() {
        return new Date().getTime()
    }
}

timetext = {
    _pyStrFormatRe: /%\((\w+)\)s/g,
    _pyStrFormat: function(format, params) {
        return format.replace(this._pyStrFormatRe, function(match, fieldName) {
            if (!(fieldName in params)) {
                throw 'missing format parameter'
            }
            return params[fieldName]
        })
    },

    _chunks: (function () {
        function P_(x, y) { return [x, y] }
        return [
            [60 * 60 * 24 * 365, ['a year ago', '%(num)s years ago']],
            [60 * 60 * 24 * 30, ['a month ago', '%(num)s months ago']],
            [60 * 60 * 24, ['a day ago', '%(num)s days ago']],
            [60 * 60, ['an hour ago', '%(num)s hours ago']],
            [60, ['a minute ago', '%(num)s minutes ago']]
        ]
    })(),

    init: function () {
        this.refresh()
        setInterval(this.refresh, 60000)
    },

    refresh: function () {
        var now = Date.now()

        $('time').each(function () {
            timetext.refreshOne(this, now)
        })
    },

    refreshOne: function (el, now) {
        if (!now)
            now = Date.now()

        var $el = $(el)
        var isoTimestamp = $el.attr('datetime')
        var timestamp = Date.parse(isoTimestamp)
        var age = (now - timestamp) / 1000
        var chunks = timetext._chunks
        var text = 'less than a minute ago'

        $.each(timetext._chunks, function (ix, chunk) {
            var count = Math.floor(age / chunk[0])
            var keys = chunk[1]
            if (count == 1) {
                text = timetext._pyStrFormat(keys[0], {num: count})
                return false
            } else if (count > 1) {
                text = timetext._pyStrFormat(keys[1], {num: count})
                return false
            }
        })

        $el.text(text)
    }
}

timetext.init()
