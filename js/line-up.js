$(function () {
  $(".favourite-button").click(async (event) => {
    event.preventDefault();
    const btn = event.target.closest(".favourite-button");
    const schedule_item_id = btn.value;
    const response = await fetch(
      `/api/schedule-item/${schedule_item_id}/favourite`,
      {
        method: "PUT",
        credentials: "include",
        headers: {
          "Content-Type": "application/json; charset=utf-8",
        },
        body: "{}",
      },
    );
    const result = await response.json();
    btn.classList.toggle("favourite-button-faved", result.is_favourite);
    btn.classList.toggle("favourite-button-unfaved", !result.is_favourite);
  });

  // Descriptions show by default for users without JavaScript. With JS we
  // collapse them and offer a toggle, remembered per browser.
  const STORAGE_KEY = "line-up-descriptions";
  const $lineup = $(".line-up");
  const $toggle = $("[data-toggle-descriptions]");
  if ($toggle.length) {
    let expanded = localStorage.getItem(STORAGE_KEY) === "expanded";
    const render = () => {
      $lineup.toggleClass("descriptions-collapsed", !expanded);
      $toggle.attr("aria-pressed", expanded ? "true" : "false");
      $toggle.text(expanded ? "Hide descriptions" : "Show descriptions");
    };
    $toggle.prop("hidden", false);
    render();
    $toggle.on("click", () => {
      expanded = !expanded;
      localStorage.setItem(STORAGE_KEY, expanded ? "expanded" : "collapsed");
      render();
    });
  }
});
