import Sortable from "sortablejs/modular/sortable.core.esm.js";

// FIXME: make this generic by type

var workshops = Sortable.create(
  document.getElementById("lottery-entries-workshops"),
  {
    ghostClass: "sortable-ghost-class",
    onEnd: async (event) => {
      const response = await fetch(
        `/api/schedule/lottery/workshop/preferences`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json; charset=utf-8",
          },
          body: JSON.stringify(workshops.toArray()),
        },
      );

      const result = await response.json();
    },
  },
);

var familyworkshops = Sortable.create(
  document.getElementById("lottery-entries-familyworkshops"),
  {
    ghostClass: "sortable-ghost-class",
    onEnd: async (event) => {
      const response = await fetch(
        `/api/schedule/lottery/familyworkshop/preferences`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json; charset=utf-8",
          },
          body: JSON.stringify(familyworkshops.toArray()),
        },
      );

      const result = await response.json();
    },
  },
);
