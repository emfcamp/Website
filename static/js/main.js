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
