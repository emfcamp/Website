function init_volunteer_schedule(data, all_roles, active_day) {
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
        var new_ele = $(document.createElement('tr'));
            cells = [
                make_cell(shift.end_time),
                make_cell(shift.venue.name),
                make_cell(shift.role.name),
                make_cell(shift.current_count + '/' + shift.max_needed),
                make_cell(make_details_button(shift))
            ];

        new_ele.append(cells);
        new_ele.attr('id', 'shift-'+shift.id);
        new_ele.click(make_open_modal_fn(shift));
        return new_ele;
    }

    function make_cell(inner) {
        return make_ele('td', inner);
    }

    function make_details_button(shift) {
        var content = shift.is_user_shift ? 'Cancel' : 'Sign Up';
        var cls = shift.is_user_shift ? 'btn-danger' : 'btn-success';

        return `<button id="shift-signup-${shift.id}" class="btn btn-block ${cls}">${content}</button>`;
    }

    function make_open_modal_fn(shift) {
        return function open_modal() {
            $('#signUp .modal-title').html('Sign up for ' + shift.role.name + ' @ ' + shift.start_time);

            $('#signUp .modal-body').empty();
            $('#signUp .modal-body').append(make_modal_details(shift));

            $('#signUp .modal-footer').empty();
            $('#signUp .modal-footer').append(make_modal_buttons(shift));

            $('#signUp').modal();
        };
    }

    function make_modal_details(shift) {
        var dl = $(document.createElement('dl')),
            res = [
                dl,
                make_ele('p', '<a href="'+shift.sign_up_url +'">More details</a>')],
            needed;

        if (shift.min_needed === shift.max_needed) {
            needed = shift.min_needed;
        } else {
            needed = shift.min_needed + ' - ' + shift.max_needed;
        }

        if (shift.is_user_shift) {
            res.unshift(make_ele('p', 'You are currently signed up to this shift'));
        }

        dl.addClass('dl-horizontal');
        dl.append([
            make_ele('dt', 'Role'), make_ele('dd', shift.role.name),
            make_ele('dt', 'Venue'), make_ele('dd', shift.venue.name),
            make_ele('dt', 'Start'), make_ele('dd', shift.start),
            make_ele('dt', 'End'), make_ele('dd', shift.end),
            make_ele('dt', 'Volunteers needed'),
            make_ele('dd', needed),
            make_ele('dt', 'Currently'), make_ele('dd', shift.current_count),
        ]);
        return res;
    }

    function make_modal_buttons(shift) {
        var close_btn = make_button('default', 'Close'),
            submit_btn = make_button('primary', (shift.is_user_shift) ? 'Cancel shift': 'Sign up');

        close_btn.attr('data-dismiss', 'modal');
        submit_btn.attr('id', 'sign-up-'+shift.id);
        submit_btn.addClass('debouce');
        submit_btn.click(make_sign_up_fn(submit_btn, shift));

        return [close_btn, submit_btn];
    }

    function make_button(btn_class, inner) {
        var btn = make_ele('btn', inner);
        btn.addClass('btn btn-'+btn_class);
        btn.attr('type', 'button');
        return $(btn);
    }

    function make_sign_up_fn(ele, shift) {
        return function (){
            var modal_body = $('#signUp .modal-body');
            ele.attr('disabled', true);

            $.post(shift.sign_up_url+'.json')
             .success(make_post_callback_fn(modal_body, ele, shift.id, "alert-info"))
             .fail(make_post_callback_fn(modal_body, ele, shift.id, "alert-danger"));
        };
    }

    function make_post_callback_fn(append_ele, btn_ele, shift_id, alert_type) {
        return function(resp) {
            var alert = make_alert(alert_type, resp.message);
            append_ele.prepend(alert);

            if (resp.warning) {
                alert = make_alert('alert-warning', resp.warning);
                append_ele.prepend(alert);
            }

            shift = get_shift(shift_id);
            if (resp.operation == 'add') {
                shift.current_count++;
                shift.is_user_shift = true;
            } else if (resp.operation == 'delete') {
                shift.current_count--;
                shift.is_user_shift = false;
            }
            update_shift(shift_id, shift);

            btn_ele.attr('disabled', false);
        };
    }

    function make_alert(alert_type, msg) {
        var alert = $(document.createElement('div'));
        alert.addClass('alert alert-dismissible fade in '+alert_type);
        alert.attr('role', 'alert');
        // Dismiss button must be the first child
        alert.html('<button type="button" class="close" data-dismiss="alert" aria-label="Close">'+
                        '<span aria-hidden="true">×</span>'+
                    '</button>'+
                    msg);
        return $(alert);
    }

    function make_ele(type, inner) {
        var new_ele = document.createElement(type);
        new_ele.innerHTML = inner;
        return $(new_ele);
    }

    function get_shift(shift_id) {
        var res;
        $.each(data, function(_, day) {
            $.each(day, function(_, hour) {
                $.each(hour, function(_, shift) {
                    if (shift_id === shift.id) {
                        res = shift;
                    }
                });
            });
        });
        return res;
    }

    function update_shift(shift_id, shift) {
        var day_index, hour_index, arr_index;
        $.each(data, function(day, day_shifts) {
            $.each(day_shifts, function(hour, hour_shifts) {
                $.each(hour_shifts, function(index, shift) {
                    if (shift_id === shift.id) {
                        day_index = day;
                        hour_index = hour;
                        arr_index = index;
                    }
                });
            });
        });
        data[day_index][hour_index][arr_index] = shift;
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

        if (!filters.show_past && new Date(shift.end) < new Date()) {
            return true;
        }

        if (filters.show_signed_up_only && !shift.is_user_shift) {
            return true;
        }

        return false;
    }

    function get_filters() {
        // TODO logic for trained/interested shifts
        var show_past = $('#show_past').prop('checked'),
            show_signed_up_only = $('#show_signed_up_only').prop('checked'),
            role_ids = [],
            raw_role_ids = $('#role-select').val() || [];

        if (raw_role_ids) {
            $.each(raw_role_ids, function (_, val) {
                role_ids.push(parseInt(val));
            });
        }

        return {
            role_ids: role_ids,
            show_past: show_past,
            show_signed_up_only: show_signed_up_only
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

    function set_roles() {
        var is_interested = $('#is_interested').prop('checked'),
            is_trained = $('#is_trained').prop('checked');

        $('#role-select').prop('selected', false);
        $.each(all_roles, function(_, role) {
            if (is_interested && !role.is_interested) {
                return;
            } else if (is_trained && !role.is_trained) {
                return;
            }

            $('#role-opt-'+role.id).prop('selected', true);
        });
        render();
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

    $('#signUp').on('hide.bs.modal', render);

    $('#is_interested').on('change', set_roles);
    $('#is_trained').on('change', set_roles);

    render();
}
