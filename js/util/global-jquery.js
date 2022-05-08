/* Shim file to import jQuery into the global scope. This has to be a separate ES6 module
    in order for subsequent imports (namely Bootstrap) to see the object in the global scope,
    as all ES6 imports are executed at the beginning of the file. */

import $ from 'jquery';

window.jQuery = $;
window.$ = $;