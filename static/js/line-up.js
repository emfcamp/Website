$(function() {
    $('.favourite-button').click(function(event) {
        var fave_icon = $('.favourite-icon', this);
        var is_fave = fave_icon.hasClass('glyphicon-heart');
        var proposal_id = $(this).attr('value');
        fetch('/api/proposal/' + proposal_id + '/favourite', {
            method: 'PUT',
            headers: {
              'Content-Type': 'application/json; charset=utf-8',
            },
            body: '{}'
        }).then(response => response.json()).then(function(result) {
            if (result.is_favourite) {
                fave_icon.removeClass('glyphicon-heart-empty').addClass('glyphicon-heart');
            } else {
                fave_icon.removeClass('glyphicon-heart').addClass('glyphicon-heart-empty');
            }
        });
        event.preventDefault();
    });

});
