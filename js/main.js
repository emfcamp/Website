// Note that we can't use the ES6 import statement here or the code ordering isn't preserved
// for some reason.
//
// Bootstrap.js requires jQuery. Solution hopefully is to get rid of jQuery and/or bootstrap.js...
var jQuery = require('jquery');
window.jQuery = jQuery;
window.$ = jQuery;

require('bootstrap');

if (typeof(EMF) != 'object') var EMF = Object();

EMF.debounce_submit = function() {
    var $t = $(this);
    setTimeout(function() {
        $t.prop('disabled', true);
        setTimeout(function() {
            $t.prop('disabled', false);
        }, 2000);
    }, 0);
};

$(function() {
    $('.debounce').on('click', EMF.debounce_submit);
});
