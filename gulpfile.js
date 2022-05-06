/**
 * Gulpfile for building static assets.
 *
 * This handles JS/CSS transpilation, minification, and other such
 * horrors. While it would be nice to do this in Python, it's just
 * not practical any more, so here we embrace the JS, god help us all.
 */

// Gulp and core plugins
const gulp = require('gulp');
const sourcemaps = require('gulp-sourcemaps');
const rename = require('gulp-rename');
const minimist = require('minimist');
const gulpif = require('gulp-if');
const buffer = require('gulp-buffer');
const tap = require('gulp-tap');
const log = require('gulplog');
const pump = require('pump');

// JS processors
const browserify = require('browserify');
const uglify = require('gulp-uglify');

// CSS processors
const postcss = require('gulp-postcss');
const postcssPresetEnv = require('postcss-preset-env');
const sass = require('gulp-dart-sass');
const cleancss = require('gulp-clean-css');

const argv = minimist(process.argv.slice(2));
const production = !!argv.production;

function js(cb) {
  pump([
    gulp.src([
      'js/main.js',
      'js/line-up.js',
      'js/schedule.js',
      'js/volunteer-schedule.js',
      'js/arrivals.js'
    ]),
    tap(function(file) {
      log.info('Bundling ' + file.path);
      file.contents = browserify(file.path, {debug: true})
        .transform('babelify', {presets: [
          ['@babel/env', {useBuiltIns: 'usage', corejs: 3}],
          '@babel/preset-react'
        ]}).bundle();
    }),
    buffer(),
    gulpif(!production, sourcemaps.init({loadMaps: true})),
    gulpif(production, uglify()),
    gulpif(!production, sourcemaps.write()),
    gulp.dest('static/js/'),
  ], cb);
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
    ]),
    gulpif(!production, sourcemaps.init()),
    sass({includePaths: ['../node_modules']}).on('error', function(err)  {
      var message = err.messageFormatted;
      if (production) {
        throw message;
      }
      process.stderr.write(message + "\n");
      this.emit('end');
    }),
    postcss(
      [
        require('postcss-input-range')(),
        postcssPresetEnv(),
      ],
    ),
    gulpif(production, cleancss()),
    rename({extname: '.css'}),
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

function watch() {
  gulp.watch('css/*.scss', {ignoreInitial: false}, css);
  gulp.watch('js/**/*.js', {ignoreInitial: false}, js);
  gulp.watch(
    ['./node_modules/@primer/octicons/build/svg/**/*.svg', './images/**/*'],
    {ignoreInitial: false},
    gulp.parallel(icons, images),
  );
}

exports.js = js;
exports.css = css;
exports.watch = watch;
exports.default = gulp.parallel(css, js, icons, images);
