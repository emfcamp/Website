function init_volunteer_schedule(data) {

    function make_row(shift, rowspan, hour) {
        var new_ele = $(document.createElement('tr'));
        var cells = [
                make_cell(shift.end_time),
                make_cell(shift.venue.name),
                make_cell(shift.role.name),
                make_cell(shift.current_count + '/' + shift.max_needed)
            ];

        if (rowspan) {
            var hour_cell = make_cell(hour);
            hour_cell.attr('rowspan', rowspan);
            cells.unshift(hour_cell);
        }

        new_ele.append(cells);
        return $(new_ele);
    }

    function make_cell(inner) {
        var new_ele = document.createElement('td');
        new_ele.innerHTML = inner;
        return $(new_ele);
    }

    function render_table(day, data){
        var days_data = data[day];
        var day_ele = $('#tbody-'+day);

        $.each(days_data, function(hour, hours_shifts) {
            var n_shifts = hours_shifts.length;
            $.each(hours_shifts, function(index, shift) {
                var row_ele = (index === 0) ? make_row(shift, n_shifts, hour)
                                            : make_row(shift);
                day_ele.append(row_ele);
            });
        });
    }

    function clear_table(day) {
        $('#tbody-'+day).empty();
    }

    $('a[data-toggle="tab"]').on('shown.bs.tab', function (e) {
        var day = $(e.target).attr('data-day');
        render_table(day, volunteer_shifts);
        var prev_day = $(e.relatedTarget).attr('data-day');
        clear_table(prev_day);
    });
}
