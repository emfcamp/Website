$(function() {
    $('.favourite-button').click(async (event) => {
        event.preventDefault();
        const btn = event.target.closest('.favourite-button');
        const event_id = btn.value;
        const response = await fetch(`/api/proposal/${event_id}/favourite`, {
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
