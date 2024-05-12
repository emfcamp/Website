import Sortable from 'sortablejs/modular/sortable.core.esm.js';

var el = document.getElementById('event-tickets');
var sortable = Sortable.create(el, {
  // animation: 150,
  ghostClass: "sortable-ghost-class",
});

sortable.option("onEnd", async (event) => {
  const response = await fetch(`/api/schedule/tickets/preferences`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
      },
      body: JSON.stringify(sortable.toArray()),
  });

  const result = await response.json();
})
