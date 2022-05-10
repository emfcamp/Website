// Bootstrap.js requires jQuery. Solution hopefully is to get rid of jQuery and/or bootstrap.js...
import './util/global-jquery.js'
import 'bootstrap';

if (typeof EMF != 'object') var EMF = Object();

EMF.debounce_submit = function () {
  var $t = $(this);
  setTimeout(function () {
    $t.prop('disabled', true);
    setTimeout(function () {
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

$(() => {
  $('*[data-range-payment-amount]').each((_idx, el) => {
    let amount = parseFloat(el.getAttribute('data-range-payment-amount'));
    let symbol = el.getAttribute('data-range-payment-currency');
    let amountText = $('#donation-range-' + el.getAttribute('name'))[0];

    function updateDonationRange(el) {
      amountText.innerHTML = `<span style="float:left">Donation: <strong>${symbol}&thinsp;${el.value}</strong></span>
          <span style="float:right">Refund: <strong>${symbol}&thinsp;${amount - el.value}</strong></span>
          <span style="clear:both">&nbsp;</span>`;

      if (amount == el.value) {
        $('#bank-details input').each((_, el) => el.setAttribute('disabled', 'true'));
        $('#bank-details')[0].style.opacity = '0.5';
      } else {
        $('#bank-details input').each((_, el) => el.removeAttribute('disabled'));
        $('#bank-details')[0].style.opacity = '1';
      }
    }
    updateDonationRange(el);

    $(el).on('input', e => updateDonationRange(el));
  });
});

$(function () {
  $('.debounce').on('click', EMF.debounce_submit);
});

$(() => {
  $('button[data-toggle]').on('click', (ev) => {
    let toggle_el = ev.currentTarget.getAttribute("data-toggle");
    $(`#${toggle_el}`).toggle();
    ev.stopPropagation();
  });
});

$(() => {
  $('#user_content_form #type').on('change', (ev) => {
    let value = $(ev.target).val();
    if (value == 'workshop' || value == 'youthworkshop') {
      $('.workshop-fields').show();
    } else {
      $('.workshop-fields').hide();
    }
  });
});