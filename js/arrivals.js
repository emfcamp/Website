import "jquery-highlight";
import DataTable from 'datatables.net-bs';

let EMF = {};

EMF.search_count = 0;
EMF.search_count_received = 0;
EMF.search_arrivals = function() {
    var query = $('#query').val();
    if ($.trim(query).length <= 1) {
        return;
    }
    EMF.search_count++;

    var data = $.post(EMF.search_url, { q: query, n: EMF.search_count })
        .done(EMF.search_arrivals_done)
        .fail(EMF.search_arrivals_fail);

};
EMF.search_arrivals_fail = function(jqXHR) {
    var data = jqXHR.responseJSON;
    $('#error-text').text(data.error);
    $('#error-description').text(data.description);
    $('#error').show();
    $('#tickets').hide();
};

EMF.search_arrivals_done = function(data) {
    var search_count = Number(data.n);
    if (search_count < EMF.search_count_received) return;
    EMF.search_count_received = search_count;

    $('#error').hide();

    if (data.location) {
        $('#query').val('');
        window.location = data.location;
        return;
    }

    if (EMF.tickets_data == undefined) {
        EMF.tickets_data = new DataTable('#tickets-data', {
            columns: [
                { data: 'name' },
                { data: 'email' },
            ],
            createdRow: function(row, data, index) {
                if (data.tickets == 0) {
                    $(row).addClass('no-tickets');
                } else if (data.completes == data.tickets) {
                    $(row).addClass('complete');
                } else if (data.completes > 0) {
                    $(row).addClass('partial');
                } else {
                    $(row).addClass('has-tickets');
                }
                var link = $('<a>').attr('href', data.url);
                $('td', row).wrapInner(link);
            },
            bFilter: false,
            bLengthChange: false,
            bSort: false,
            bPaginate: false,
            bAutoWidth: false,
            searchHighlight: true
        });
    }
    EMF.tickets_data.clear();
    EMF.tickets_data.settings()[0].oPreviousSearch.sSearch = $('#query').val();
    EMF.tickets_data.rows.add(data.users).draw();
};

EMF.cancel_return = function(e) {
    if (e.keyCode == 13) {
        e.cancelBubble = true;
        return false;
    }
};
EMF.search_timer = null;
EMF.delay_search_arrivals = function() {
    if (EMF.timer) {
        clearTimeout(EMF.timer);
        EMF.timer = null;
    }
    EMF.timer = setTimeout(function() {
        EMF.search_timer = null;
        EMF.search_arrivals();
    }, 250);
};
$(function() {
    const configEl = document.querySelector('#arrivals-config');
    if (!configEl) return;
    const config = JSON.parse(configEl.textContent);
    EMF.arrivalsMode = config.arrivalsMode;
    EMF.search_url = config.searchURL;

    $('#query').on('change keyup', EMF.delay_search_arrivals)
               .on('keydown', EMF.cancel_return)
               .focus();
});
