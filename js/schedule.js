var emf_scheduler = {};
window.init_emf_scheduler = (schedule_data, venues, is_anonymous) => {
    'use strict';

    var todays_date = new Date(),
        start_date = new Date(2018, 7, 31),
        end_date = new Date(2018, 8, 3),
        filter = {
            'venues': [],
            'is_favourite': false
        },
        venue_dict = {},
        timeline_venues = [
            {key:'main-schedule-items', label:'Main', open: true, children: []},
            {key:'village-schedule-items', label:'Villages', open: true, children: []},
        ],
        day_format = "%D, %j %M",   // e.g. Friday, 5th (FIXME: deal with 1st and 2nd)
        day_formatter = scheduler.date.date_to_str(day_format),
        time_formatter = scheduler.date.date_to_str("%H:%i"), // e.g. 22:33
        debounce = false,
        date_to_show = (todays_date >= start_date && todays_date <= end_date) ? todays_date : start_date,
        main_venues = [
            {"key": "Stage-A", "label": "Stage A"},
            {"key": "Stage-B", "label": "Stage B"},
            {"key": "Stage-C", "label": "Stage C"},
            {"key": "Workshop-1", "label": "Workshop 1"},
            {"key": "Workshop-2", "label": "Workshop 2"},
            {"key": "Workshop-3", "label": "Workshop 3"},
            {"key": "Workshop-4", "label": "Workshop 4"}
        ],
        id, ele, id_str, ven;

    /*
     * Required config
     */
    // Make sure dates are parsed correctly
    scheduler.config.api_date = "%Y-%m-%d %H:%i:%s";
    scheduler.config.xml_date = "%Y-%m-%d %H:%i:%s";

    // We used the all_timed extension to show events that cross the midnight
    // event horizon
    scheduler.config.multi_day = true;
    scheduler.config.all_timed = true;

    /*
     * Views
     */
    // Initialise a load of stuff
    // Easily retrieve venue name from its ID
    for(var i = 0; i<venues.length; i++){
        ven = venues[i];
        venue_dict[ven.key] = ven;
        filter.venues.push(ven.key);

        id_str = 'venue_'+ven.key;

        ele = $('#filters').append(
            '<div class="checkbox">' +
                '<label>' +
                  '<input id="'+id_str+'" type="checkbox"> ' + ven.label +
                '</label>' +
            '</div>'
        );

        ele = $('#' + id_str)[0];
        ele.checked = true;
        ele.onchange = _get_onchange(ven.key);

        if (ven.source === 'main') {
            timeline_venues[0].children.push(ven);
        } else {
            timeline_venues[1].children.push(ven);
        }
    }

    ele = $('#is_favourite')[0].onchange = function() {
        filter.is_favourite = !filter.is_favourite;
        scheduler.updateView();
    };

    function _sortVenues(a, b) {
        var venueA = (typeof a === 'object') ? a : venue_dict[a],
            venueB = (typeof b === 'object') ? b :venue_dict[b];

        if (venueA.source !== venueB.source) {
            return venueA.source === 'ical' ? 1 : -1;
        } else if (venueA.order != venueB.order) {
            return venueA.order < venueB.order ? 1: -1;
        }
        return venueA.key > venueB.key ? 1: -1;
    }

    function _get_onchange(id){
        return function() {
            var index = filter.venues.indexOf(id),
                venue_index = venues.indexOf(venue_dict[id]);

            if (index >= 0) {
                filter.venues.splice(index, 1);
                venues.splice(index, 1);
            } else {
                filter.venues.push(id);
                venues.push(venue_dict[id]);
                venues.sort(_sortVenues);

                filter.venues.sort(_sortVenues);
            }
            scheduler.updateCollection('venues', venues);
            scheduler.updateView();
        };
    }
    // Configure venues view
    scheduler.locale.labels.emf_day_tab = "Day";
    scheduler.locale.labels.section_custom="Section";
    scheduler.createUnitsView({
        name: "emf_day",
        property: "venue",
        list: scheduler.serverList('venues', venues),
        size: 8,
        step: 1,
    });

    scheduler.locale.labels.emf_timeline_tab = "All Events";
    scheduler.createTimelineView({
        section_autoheight: false,
        name:"emf_timeline",
        // Width of initial column
        dx: 150,
        x_unit: "minute",
        x_date: "%H:%i",
        x_step: 60,
        x_size: 15,
        x_start: 9,
        x_length: 24,
        y_unit: scheduler.serverList('venues', timeline_venues),
        y_property: "venue",
        render: "tree",
        folder_dy:20,
        dy:40
    });

    scheduler.templates.emf_timeline_date = function(start_day, end_day) {
        return day_formatter(start_day);
    };

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
        if (ev.speaker.trim() == '') {
            $('#event_speaker_wrapper').hide();
        } else {
            $('#event_speaker').text(ev.speaker);
            $('#event_speaker_wrapper').show();
        }

        $('#event_venue').text(venue_dict[ev.venue].label);
        $('#event_venue').attr('href', ev.map_link);
        $('#event_day').text(day_formatter(ev.start_date));
        $('#event_time').text(time_formatter(ev.start_date));
        $('#event_description').html(ev.description);

        if (ev.type === 'workshop' && ev.cost.trim() !== '') {
            var cost = $('<span class="event-cost">').text(ev.cost);
            $('#workshop_cost').html('<strong>Cost:</strong> ' + cost.html());
            $('#workshop_requirements').html('<strong>Requirements:</strong> ' + ev.equipment);
        } else {
            $('#workshop_cost').html('');
            $('#workshop_requirements').html('');
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
    // First hour to show
    scheduler.config.scroll_hour = 9;
    // If there's enough space show hours with 10 minute divisions
    scheduler.config.hour_size_px = ($(window).width() <= 768) ? 88: 132; //132;
    // scheduler.config.hour_size_px = 132;
    scheduler.config.separate_short_events = true;

    // Format the tooltips
    scheduler.templates.tooltip_text = function(start, end, event) {
        return "<b>Event:</b> " + event.text + "<br/>"+
               "<b>Start:</b> " + time_formatter(start) + "<br/>"+
               "<b>Finish:</b> " + time_formatter(end) + "<br/>"+
               "<b>Venue:</b> " + venue_dict[event.venue].label;
    };

    // Add custom CSS classes based on the event properties
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
    function _sizeScheduler(){
        var view_height = window.innerHeight||document.documentElement.clientHeight,
            header_offset = get_ele('header').offsetTop,
            header_height = get_ele('header').offsetHeight + header_offset,
            footer_height = 50,
            schedule_height = view_height - header_height - footer_height,
            schedule = get_ele('scheduler_here');

        scheduler.config.hour_size_px = ($(window).width() <= 768) ? 88: 132; //132;
        scheduler.updateView();
        schedule.style.height = schedule_height + 'px';
    }

    // Apparently this is what we need to use if we'd like to detect when
    // the screen is rendered
    scheduler.attachEvent("onViewChange", function () {
        _sizeScheduler();
        emf_scheduler.size_scheduler = _sizeScheduler;
        window.onresize = _sizeScheduler;
    });

    window.onclick = function (mouseEvent) {
        if (mouseEvent.target.className.indexOf('dhx_cal_cover') !== -1) {
            _close_popup();
        }
    };

    var initial_view = 'emf_day';

    scheduler.init('scheduler_here', date_to_show, initial_view);
    scheduler.parse(schedule_data, 'json');

    // Seems not to be happening on load
    _sizeScheduler();
};
