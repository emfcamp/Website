function init_volunteer_schedule(data, active_day) {
    var current_day = active_day;

    function render_table(day, data){
        var filters = get_filters();
        var days_data = data[day];
        var day_ele = $('#tbody-'+day);

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
        var new_ele = $(document.createElement('tr'));
        var cells = [
                make_cell(shift.end_time),
                make_cell(shift.venue.name),
                make_cell(shift.role.name),
                make_cell(shift.current_count + '/' + shift.max_needed)
            ];

        new_ele.append(cells);
        return $(new_ele);
    }

    function make_cell(inner) {
        var new_ele = document.createElement('td');
        new_ele.innerHTML = inner;
        return $(new_ele);
    }

    function clear_filters() {
        $('#role-select > option').each(function(_, ele) {
            $(ele).attr('selected', false);
        });
    }

    function apply_filters() {
         $('#tbody-'+current_day).empty();
        render_table(current_day, volunteer_shifts);
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

    // On tab change
    $('a[data-toggle="tab"]').on('shown.bs.tab', function (e) {
        current_day = $(e.target).attr('data-day');
        render_table(current_day, volunteer_shifts);


        // Clear the old stuff
        var prev_day = $(e.relatedTarget).attr('data-day');
        $('#tbody-'+prev_day).empty();
    });

    $('#filter-btn').click(apply_filters);
    $('#clear-btn').click(clear_filters);
}
