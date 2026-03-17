$(function() {
    $('.favourite-button').click(async (event) => {
        event.preventDefault();
        const btn = event.target.closest('.favourite-button');
        const schedule_item_id = btn.value;
        const response = await fetch(`/api/schedule-item/${schedule_item_id}/favourite`, {
            method: 'PUT',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json; charset=utf-8',
            },
            body: '{}',
        });
        const result = await response.json();
        btn.classList.toggle('favourite-button-faved', result.is_favourite);
        btn.classList.toggle('favourite-button-unfaved', !result.is_favourite);
    });
});
