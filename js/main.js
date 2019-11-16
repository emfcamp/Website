// Note that we can't use the ES6 import statement here or the code ordering isn't preserved
// for some reason.
//
// Bootstrap.js requires jQuery. Solution hopefully is to get rid of jQuery and/or bootstrap.js...
var jQuery = require('jquery');
window.jQuery = jQuery;
window.$ = jQuery;

require('bootstrap');

if (typeof EMF != 'object') var EMF = Object();

EMF.debounce_submit = function() {
  var $t = $(this);
  setTimeout(function() {
    $t.prop('disabled', true);
    setTimeout(function() {
      $t.prop('disabled', false);
    }, 2000);
  }, 0);
};

$(() => {
  $('*[data-word-limit]').each((_idx, el) => {
    let limit = parseInt(el.getAttribute('data-word-limit'));
    let limitText = $('#word-limit-' + el.getAttribute('name'));

    function updateWordLimit(el) {
        let currentLength = el.value.trim().split(/\s+/).length;
        if (el.value == '') {
          currentLength = 0;
        }
        limitText.innerHTML = currentLength + "/" + limit + " words";
    }

    if (!limitText) {
      console.log('No word limit text element for ' + el);
      return;
    }
    limitText = limitText[0];

    updateWordLimit(el);

    $(el).on('beforeinput', e => {
      if (e.originalEvent.data == null) {
        return;
      }
      let newText = el.value + e.originalEvent.data;
      let words = newText.trim().split(/\s+/);
      if (words.length > limit) {
        el.value = words.slice(0, limit).join(' ');
        updateWordLimit(el);
        return false;
      }
    });

    $(el).on('input', e => updateWordLimit(el));
  });
});

$(function() {
  $('.debounce').on('click', EMF.debounce_submit);
});
