
var emf_scheduler = {};
function init_emf_scheduler(schedule_data, venues, is_anonymous){
    'use strict';

    var todays_date = new Date(),
        start_date = new Date(2016, 7, 5),
        end_date = new Date(2016, 7, 8),
        filter = {
            'venues': [],
            'is_favourite': false
        },
        venue_dict = {},
        day_format = "%D, %jth",   // e.g. Friday, 5th (FIXME: deal with 1st and 2nd)
        day_formatter = scheduler.date.date_to_str(day_format),
        time_formatter = scheduler.date.date_to_str("%H:%i"), // e.g. 22:33
        debounce = false,
        date_to_show = (start_date <= todays_date) ? todays_date : start_date,
        week_or_day = (start_date <= todays_date && end_date >= todays_date) ? 'emf_day' : 'emf_weekend',
        id, ele, id_str;

    /*
     * Required config
     */
    // Make sure dates are parsed correctly
    scheduler.config.api_date = "%Y-%m-%d %H:%i:%s";
    scheduler.config.xml_date = "%Y-%m-%d %H:%i:%s";

    // Nothing scheduled is multi-day so switch it off
    scheduler.config.multi_day = false;

    /*
     * Views
     */
    // Configure venues view
    scheduler.locale.labels.emf_day_tab = "Day";
    scheduler.locale.labels.section_custom="Section";
    scheduler.createUnitsView({
        name: "emf_day",
        property: "venue",
        list: scheduler.serverList('venues', venues),
        size: 5,
        step: 3,
    });

    scheduler.locale.labels.emf_weekend_tab = "Weekend";
    scheduler.createUnitsView({
        name:"emf_weekend",
        property:"venue",
        list: scheduler.serverList('venues', venues),
        days: 3,
    });

    // Easily retrieve venue name from its ID
    for(var i = 0; i<venues.length; i++){
        venue_dict[venues[i].key] = venues[i].label;
        filter.venues.push(venues[i].key);

        id_str = 'venue_'+venues[i].key;

        ele = $('#filters').append(
            '<div class="checkbox">' +
                '<label>' +
                  '<input id="'+id_str+'" type="checkbox"> ' + venues[i].label +
                '</label>' +
            '</div>'
        );

        ele = $('#' + id_str)[0];
        ele.checked = true;
        ele.onchange = _get_onchange(venues[i].key);
    }

    ele = $('#is_favourite')[0].onchange = function() {
        filter.is_favourite = !filter.is_favourite;
        scheduler.updateView();
    };

    function _get_onchange(id){
        return function() {
            var index = filter.venues.indexOf(id),
                venue_index = venues.indexOf(venue_dict[id]);

            if (index >= 0) {
                filter.venues.splice(index, 1);
                venues.splice(index, 1);
            } else {
                filter.venues.push(id);
                venues.push({key:id, label: venue_dict[id]});
                venues.sort(function (a, b) {
                    return a.key === b.key ? 0 :
                           a.key > b.key ? 1 : -1;
                });

                filter.venues.sort(function (a, b) {
                    return venue_dict[a] === venue_dict[b] ? 0 :
                           venue_dict[a] > venue_dict[b] ? 1 : -1;
                });
            }
            scheduler.updateCollection('venues', venues);
            scheduler.updateView();
        };
    }

    // Set the filter for both views
    function _filter_events(id, event){
        var test_venues = filter.venues,
            test_fave = filter.is_favourite,
            is_favourite = test_fave ?
                           event.is_fave :
                           true,
            is_venue = test_venues.indexOf(event.venue) >= 0;

        return is_favourite && is_venue;
    }
    scheduler.filter_emf_day = _filter_events;
    scheduler.filter_emf_weekend = _filter_events;

    // Clamp day view
    scheduler.date.add_emf_day = function (day, inc) {
        var res = scheduler.date.add(day, inc, "day"),
            last_day = new Date(end_date);

        // end date is Monday (to set inclusive ranges) last day is Sunday
        last_day.setUTCDate(end_date.getUTCDate() - 1);

        // Test on the date value so we can compare using less/greater than
        // or equals
        if (res.getUTCDate() <= start_date.getUTCDate()) {
            return start_date;
        } else if (res.getUTCDate() >= last_day.getUTCDate()) {
            return last_day;
        }
        return res;
    };

    // Make sure in weekend view you can't scroll away
    scheduler.date.add_emf_weekend = function (date,inc) {
        return scheduler.date.add(start_date, venues.length*3 ,"day");
    };

    scheduler.date.get_emf_weekend_end = function (date) {
        return scheduler.date.add(start_date, venues.length*3 ,"day");
    };

    scheduler.date.get_emf_weekend_start = function (date) {
        return start_date;
    };

    scheduler._click.dhx_cal_tab = function () {
        // Override the view toggle so that it always locks weekend view to
        // Friday
        var name = this.getAttribute("name"),
            mode = name.substring(0, name.search("_tab")),
            date = (mode === "emf_weekend" ) ? start_date : scheduler._date;
        scheduler.setCurrentView(date, mode);
    };

    // scheduler._click.dhx_second_scale_bar = function () {
    //     console.log(arguments);
    //     scheduler.setCurrentView(date, 'emf_day');
    // };

    // scheduler.date.week_emf_day_start = scheduler.date.week_start;

    // There'll be no events outside the weekend so lock the view to it
    scheduler.config.limit_view = true;
    scheduler.config.limit_start = start_date;
    scheduler.config.limit_end  = end_date;

    /*
     * Make it read-only
     */
    // This is read only so block all modifications
    scheduler.config.readonly_form = true;
    scheduler.config.details_on_dblclick = true;
    scheduler.config.dblclick_create = false;
    scheduler.attachEvent("onBeforeDrag",function(){ return false; });
    scheduler.attachEvent("onClick",function (id){
        scheduler.showLightbox(id);
        return false;// block further actions
    });

    /*
     * Custom popup
     */
    scheduler.showCover = function showCover(box){
        var view_height = window.innerHeight||document.documentElement.clientHeight,
            schedule_top = get_ele('scheduler_here').offsetTop,
            schedule_height = get_ele('scheduler_here').offsetHeight,
            margin = view_height > 768 ? 150 : 75;

        if (box){
            box.style.display="block";

            var top = schedule_top + margin,
                bottom = view_height - margin,
                difference = bottom - top,
                scroll = get_ele('scroll_box'),
                max_height = difference - (scroll.offsetTop + 40);

            scroll.style['max-height'] = max_height + 'px';

        }
        this.show_cover();
    };

    var get_ele = function (id) { return document.getElementById(id); },
        popup_event;

    scheduler.showLightbox = function(id) {
        var ev = scheduler.getEvent(id);

        // Open the popup
        scheduler.startLightbox(id, document.getElementById("event_popup"));

        // Set the basic details
        $('#event_title').text(ev.title);
        $('#event_speaker').text(ev.speaker);

        $('#event_venue').text(venue_dict[ev.venue]);
        $('#event_day').text(day_formatter(ev.start_date));
        $('#event_time').text(time_formatter(ev.start_date));
        $('#event_description').html(ev.description);

        if (ev.type === 'workshop' && ev.cost.trim() !== '') {
            var cost = $('<span class="event-cost">').text(ev.cost);
            $('#workshop_cost').html('<strong>Cost:</strong> ' + cost.html());
        } else {
            $('#workshop_cost').html('');
        }

        // Set the link and indicate whether this is a faved event
        $('#title_link').attr('href', ev.link);
        $('#favourite_form').attr('action', ev.link);
        $('#favourite_icon').removeClass('glyphicon-star glyphicon-star-empty');
        $('#favourite_icon').addClass(ev.is_fave ? 'glyphicon-star' : 'glyphicon-star-empty');

        if ( is_anonymous ) {
            $('#favourite_btn').hide();
            $('#loggedout').show();
        }

        popup_event = ev;
    };

    function _close_popup(){
        scheduler.endLightbox(false, get_ele("event_popup"));
        popup_event = null;
    }

    emf_scheduler.close_popup = function close_popup() {
        _close_popup();
    };

    emf_scheduler.favourite = function favourite() {
        if (debounce) { return; }

        var http = new XMLHttpRequest(),
            form = get_ele('favourite_form'),
            csrf = get_ele('csrf_token'),
            fave = get_ele('favourite_icon'),
            event = popup_event.id;

        http.open("POST", form.action, true);
        http.setRequestHeader("Content-type","application/x-www-form-urlencoded");

        var params = csrf.name + '=' + csrf.value;
        http.send(params);
        debounce = true;
        setTimeout(function() {
            debounce = false;
        }, 250);

        popup_event.is_fave = !popup_event.is_fave;

        fave.className = popup_event.is_fave ? "glyphicon glyphicon-star" :
                                               "glyphicon glyphicon-star-empty";

        scheduler.updateEvent(popup_event.id);
    };

    $(document).keyup(function(e){
        _close_popup();
    });

    /*
     * Styles
     */
    // Set the date format
    scheduler.config.show_loading = true;
    scheduler.config.default_date = day_format;
    // Make it show 10 min slots
    scheduler.config.first_hour = 9;
    scheduler.config.hour_size_px = 131;
    scheduler.config.separate_short_events = true;

    // Format the tooltips
    scheduler.templates.tooltip_text = function(start, end, event) {
        return "<b>Event:</b> " + event.text + "<br/>"+
               "<b>Start date:</b> " + time_formatter(start) + "<br/>"+
               "<b>End date:</b> " + time_formatter(end) + "<br/>"+
               "<b>Venue:</b> " + venue_dict[event.venue];
    };

    scheduler.templates.event_class=function(start,end,event){
        var res = [];

        if (start < new Date() ) {
            res.push('past_event');
        }
        if (event.is_fave ) {
            res.push('favourite');
        }
        return res.join(' ');
    };

    emf_scheduler.size_scheduler = function size_scheduler(){
        var view_height = window.innerHeight||document.documentElement.clientHeight,
            header_offset = get_ele('header').offsetTop,
            header_height = get_ele('header').offsetHeight + header_offset,
            schedule_height = view_height - header_height,
            schedule = get_ele('scheduler_here');
        schedule.style.height = schedule_height + 'px';
    };

    scheduler.attachEvent("onSchedulerReady", emf_scheduler.size_scheduler);
    window.onresize = emf_scheduler.size_scheduler;

    window.onclick = function (mouseEvent) {
        if (mouseEvent.target.className.indexOf('dhx_cal_cover') !== -1) {
            _close_popup();
        }
    };

    if ($(window).width() <= 1024) {
        week_or_day = 'emf_day';
    }

    scheduler.init('scheduler_here', date_to_show, week_or_day);
    scheduler.parse(schedule_data, 'json');
}