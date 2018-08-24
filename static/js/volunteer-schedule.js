function init_volunteer_schedule(data, active_day) {
    var current_day = active_day;

    function render(){
        var filters = get_filters(),
            days_data = data[current_day],
            day_ele = $('#tbody-'+current_day);

        day_ele.empty();

        $.each(days_data, function(hour, hours_shifts) {
            var n_shifts = hours_shifts.length,
                rows = [];

            $.each(hours_shifts, function(index, shift) {
                if (fails_filters(filters, shift)) {
                    return;
                }
                rows.push(make_row(shift));
            });

            if (rows.length > 0) {
                prepend_hour_cell(rows[0], hour, rows.length);
                day_ele.append(rows);
            }
        });
    }

    function prepend_hour_cell(row, hour, rowspan) {
        var cell = make_cell(hour);
        cell.attr('rowspan', rowspan);
        row.prepend(cell);
        return row;
    }

    function make_row(shift) {
        var new_ele = $(document.createElement('tr')),
            cells = [
                make_cell(shift.end_time),
                make_cell(shift.venue.name),
                make_cell(shift.role.name),
                make_cell(shift.current_count + '/' + shift.max_needed)
            ];

        new_ele.append(cells);
        new_ele.attr('id', 'shift-'+shift.id);
        new_ele.click(function() {
            $('#signUp .modal-title').html('Sign up for ' + shift.role.name + ' @ ' + shift.start_time);
            $('#signUp .modal-body').empty();
            $('#signUp .modal-body').append(make_modal_body(shift));
            $('#signUp').modal();
        });
        return new_ele;
    }

    function make_cell(inner) {
        return make_ele('td', inner);
    }

    function make_modal_body(shift) {
        var dl = $(document.createElement('dl')),
            needed = (shift.min_needed === shift.max_needed)? shift.min_needed
                                                            : shift.min_needed + ' - ' + shift.max_needed;
        dl.addClass('dl-horizontal');
        dl.append([
            make_ele('dt', 'Role'), make_ele('dd', shift.role.name),
            make_ele('dt', 'Venue'), make_ele('dd', shift.venue.name),
            make_ele('dt', 'Start'), make_ele('dd', shift.start),
            make_ele('dt', 'End'), make_ele('dd', shift.end),
            make_ele('dt', 'Volunteers needed'),
            make_ele('dd', needed),
            make_ele('dt', 'Currently'),  make_ele('dd', shift.current_count)
        ]);
        return dl;
    }

    function make_ele(type, inner) {
        var new_ele = document.createElement(type);
        new_ele.innerHTML = inner;
        return $(new_ele);
    }

    function clear_filters() {
        $('#role-select > option').each(function(_, ele) {
            $(ele).attr('selected', false);
        });
    }

    function fails_filters(filters, shift) {
        if (filters.role_ids.length > 0 && !is_in(filters.role_ids, shift.role_id)) {
            return true;
        }

        if (!filters.show_past && shift.end_time < new Date()) {
            return true;
        }

        return false;
    }

    function get_filters() {
        // TODO logic for trained/interested shifts
        var show_past = $('#show_past').val() || false,
            role_ids = [],
            raw_role_ids = $('#role-select').val();

        if (raw_role_ids) {
            $.each(raw_role_ids, function (_, val) {
                role_ids.push(parseInt(val));
            });
        }

        return {
            role_ids: role_ids,
            show_past: show_past
        };
    }

    function is_in(arr, test){
        var res = false;

        if (!arr || !test) {
            return false;
        }

        $.each(arr, function(_, val){
            if (test === val) {
                res = true;
            }
        });
        return res;
    }


    ////////////////////////////////////
    //
    //
    // Set up events
    //
    ////////////////////////////////////

    // On tab change
    $('a[data-toggle="tab"]').on('shown.bs.tab', function (e) {
        current_day = $(e.target).attr('data-day');
        render();

        // Clear the old stuff
        var prev_day = $(e.relatedTarget).attr('data-day');
        $('#tbody-'+prev_day).empty();
    });

    // Filter buttons
    $('#filter-btn').click(render);
    $('#clear-btn').click(clear_filters);

    render();
}
