import Sortable from 'sortablejs/modular/sortable.core.esm.js';

var workshops = Sortable.create(
  document.getElementById('event-tickets-workshops'),
  {
    ghostClass: "sortable-ghost-class",
    onEnd:  async (event) => {
      const response = await fetch(`/api/schedule/tickets/preferences`, {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json; charset=utf-8',
          },
          body: JSON.stringify(workshops.toArray()),
      });

      const result = await response.json();
    },
  },
);

var youthworkshops = Sortable.create(
  document.getElementById('event-tickets-youthworkshops'),
  {
    ghostClass: "sortable-ghost-class",
    onEnd:  async (event) => {
      const response = await fetch(`/api/schedule/tickets/preferences`, {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json; charset=utf-8',
          },
          body: JSON.stringify(youthworkshops.toArray()),
      });

      const result = await response.json();
    },
  },
);

