function applyDeleteState(checkbox) {
  var fieldset = checkbox.closest("fieldset");
  var label = fieldset.querySelector(".delete-row-label");
  var deleting = checkbox.checked;
  fieldset.style.opacity = deleting ? "0.4" : "";
  label.classList.toggle("active", deleting);
  fieldset
    .querySelectorAll(
      "input:not(.delete-row-checkbox):not([type=hidden]), select, textarea",
    )
    .forEach(function (el) {
      if (deleting) {
        var text =
          el.tagName === "SELECT"
            ? el.selectedIndex >= 0
              ? el.options[el.selectedIndex].text
              : ""
            : el.value;
        var span = document.createElement("span");
        span.className = "delete-preview";
        span.textContent = text;
        el.parentNode.insertBefore(span, el);
        el.style.display = "none";
        el.disabled = true;
      } else {
        var preview = el.parentNode.querySelector(".delete-preview");
        if (preview) preview.remove();
        el.style.display = "";
        el.disabled = false;
      }
    });
}

function bindDeleteCheckbox(checkbox) {
  checkbox.addEventListener("change", function () {
    applyDeleteState(this);
  });
  applyDeleteState(checkbox);
}

document.querySelectorAll(".delete-row-checkbox").forEach(bindDeleteCheckbox);

var newRowCount = document.querySelectorAll(
  "#shift-templates-body [data-is-new]",
).length;

function addNewRow(sourceFieldset) {
  var tmpl = document.getElementById("new-row-template");
  var clone = document.importNode(tmpl.content, true);
  var prefix = "template-new-" + newRowCount + "-";
  clone.querySelectorAll("[name]").forEach(function (el) {
    el.name = el.name.replace("template-new-", prefix);
  });
  var fieldset = clone.querySelector("fieldset");
  if (sourceFieldset) {
    var srcInputs = sourceFieldset.querySelectorAll(
      "input:not(.delete-row-checkbox):not([type=hidden]), select, textarea",
    );
    var dstInputs = fieldset.querySelectorAll(
      "input:not(.delete-row-checkbox):not([type=hidden]), select, textarea",
    );
    srcInputs.forEach(function (src, i) {
      if (dstInputs[i]) dstInputs[i].value = src.value;
    });
  }
  document.getElementById("shift-templates-body").appendChild(clone);
  bindDeleteCheckbox(fieldset.querySelector(".delete-row-checkbox"));
  bindCloneButton(fieldset.querySelector(".clone-row-btn"));
  newRowCount++;
}

function bindCloneButton(btn) {
  btn.addEventListener("click", function () {
    addNewRow(this.closest("fieldset"));
  });
}

document.querySelectorAll(".clone-row-btn").forEach(bindCloneButton);

document
  .getElementById("add-template-btn")
  .addEventListener("click", function () {
    addNewRow(null);
  });
