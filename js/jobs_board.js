$(() => {
  var table = document.getElementById('jobs-table');
  if(table) {
    Array.from(table.rows).forEach(row => {
      row.addEventListener("click", function() {
        window.open(this.getAttribute('data-href'), "_blank");
      });
    });
  }
});
