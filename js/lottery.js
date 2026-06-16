import Sortable from "sortablejs/modular/sortable.core.esm.js";

const types = ["workshop", "familyworkshop"];

for (const type of types) {
  console.log(type);
  const block = document.getElementById(`lottery-entries-${type}`);
  console.log(block);
  if (!block) continue;

  const sortable = Sortable.create(block, {
    ghostClass: "sortable-ghost-class",
    onEnd: async (event) => {
      const response = await fetch(
        `/api/schedule/lottery/${type}/preferences`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json; charset=utf-8",
          },
          body: JSON.stringify(sortable.toArray()),
        },
      );

      const result = await response.json();
    },
  });
}
