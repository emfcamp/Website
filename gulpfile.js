/**
 * Gulpfile for building static assets.
 *
 * This handles JS/CSS transpilation, minification, and other such
 * horrors. While it would be nice to do this in Python, it's just
 * not practical any more, so here we embrace the JS, god help us all.
 */

// Gulp and core plugins
import gulp from 'gulp';
import rename from 'gulp-rename';
import minimist from 'minimist';
import gulpif from 'gulp-if';
import buffer from 'vinyl-buffer';
import pump from 'pump';
import source from 'vinyl-source-stream';

// JS processors
import sourcemaps from 'gulp-sourcemaps';
import rollup from '@rollup/stream';
import { babel } from '@rollup/plugin-babel';
import commonjs from '@rollup/plugin-commonjs';
import json from '@rollup/plugin-json';
import { nodeResolve } from '@rollup/plugin-node-resolve';
import replace from '@rollup/plugin-replace';
import uglify from 'gulp-uglify';

// CSS processors
import postcss from 'gulp-postcss';
import postcssPresetEnv from 'postcss-preset-env';
import postcssInputRange from 'postcss-input-range';
import sass from 'gulp-dart-sass';
import cleancss from 'gulp-clean-css';

const argv = minimist(process.argv.slice(2));
const production = !!argv.production;

// Cache for Rollup bundles to speed up rebuilds.
let rollup_cache = {};

function jsBuild(filename) {
  // Javascript file build pipeline.
  // This is called once per target file. You can pass multiple files into Rollup but
  // it does something clever with them, which we don't (currently) want.
  return [
    // Rollup.js collects all the Javascript dependencies and combines them into a single
    // bundle (we previously used browserify here).
    rollup({
      input: `js/${filename}`,
      output: {
        // The "iife" format is the most compatible one for browsers, but we should try
        // moving to ES6 modules here soon.
        format: "iife",
        sourcemap: true,
        name: filename.replace(/\.js$/, '').replace(/-/g, '_'),
      },
      cache: rollup_cache[filename],
      plugins: [
        nodeResolve(), // Resolve NPM modules
        json(), // Convert JSON imports to JS
        commonjs(), // Convert commonJS (old-style) imports into ES6 imports which Rollup understands.
        replace({ // Replace strings in JS
          // NODE_ENV is used by React to determine whether to use production or development
          'process.env.NODE_ENV': JSON.stringify(production ? 'production' : 'development'),
          // Keys below are options to the replace plugin rather than variables to replace.
          'preventAssignment': true,
        }),
        babel({ // Transpiles JS/JSX to a format hopefully understood by browsers.
          presets: [["@babel/preset-env", { useBuiltIns: 'usage', corejs: 3 }], "@babel/preset-react"],
          babelHelpers: "bundled",
          exclude: [/\/core-js\//]
        }),
      ]
    }).on('bundle',
      (bundle) => {
        rollup_cache[filename] = bundle;
      }
    ),
    source(filename),
    buffer(),
    gulpif(!production, sourcemaps.init({ loadMaps: true })),
    gulpif(production, uglify()),
    gulpif(!production, sourcemaps.write()),
    gulp.dest('static/js/'),
  ];
}

// This is the list of all the JS files we want to output.
// We need to name these functions to get gulp to put sensible names in the CLI output.
const main_js = (cb) => pump(jsBuild('main.js'), cb),
  line_up_js = (cb) => pump(jsBuild('line-up.js'), cb),
  schedule_js = (cb) => pump(jsBuild('schedule.js'), cb),
  volunteer_schedule_js = (cb) => pump(jsBuild('volunteer-schedule.js'), cb),
  event_tickets_js = (cb) => pump(jsBuild('event-tickets.js'), cb),
  arrivals_js = (cb) => pump(jsBuild('arrivals.js'), cb);


function js(cb) {
  gulp.parallel(main_js, line_up_js, schedule_js, volunteer_schedule_js, event_tickets_js, arrivals_js)(cb);
}

function css(cb) {
  pump([
    gulp.src([
      'css/admin.scss',
      'css/arrivals.scss',
      'css/invoice.scss',
      'css/main.scss',
      'css/receipt.scss',
      'css/schedule.scss',
      'css/volunteer_schedule.scss',
      'css/flask-admin.scss',
      'css/dhtmlxscheduler_flat.css',
    ]),
    gulpif(!production, sourcemaps.init()),
    sass({ includePaths: ['../node_modules'] }).on('error', function (err) {
      var message = err.messageFormatted;
      if (production) {
        throw message;
      }
      process.stderr.write(message + "\n");
      this.emit('end');
    }),
    postcss(
      [
        postcssInputRange(),
        postcssPresetEnv(),
      ],
    ),
    gulpif(production, cleancss()),
    rename({ extname: '.css' }),
    gulpif(!production, sourcemaps.write()),
    gulp.dest('static/css'),
  ], cb);
}

function icons(cb) {
  pump([
    gulp.src('./images/**/*'),
    gulp.dest('static/images'),
  ], cb);
}

function images(cb) {
  pump([
    gulp.src('./node_modules/@primer/octicons/build/svg/**/*.svg'),
    gulp.dest('static/icons'),
  ], cb);
}

function manifest(cb) {
  pump([
    gulp.src('./manifest.json'),
    gulp.dest('static'),
  ], cb);
}

function watch() {
  gulp.watch('css/*.scss', { ignoreInitial: false }, css);
  gulp.watch(['js/**/*.js', 'js/**/*.jsx'], { ignoreInitial: false }, js);
  gulp.watch(
    ['./node_modules/@primer/octicons/build/svg/**/*.svg', './images/**/*'],
    { ignoreInitial: false },
    gulp.parallel(icons, images),
  );
  gulp.watch('./manifest.json', { ignoreInitial: false }, manifest);
}

export { js, css, watch };
export default gulp.parallel(css, js, icons, images, manifest);
