import { defineConfig } from '@rsbuild/core';
import { pluginSass } from '@rsbuild/plugin-sass';

class SCSSNoOutputPlugin {
    apply(compiler) {
        compiler.hooks.thisCompilation.tap('SCSSNoOutputPlugin', compilation => {
            const { Compilation } = compiler.rspack;
            compilation.hooks.processAssets.tap({
                name: 'SCSSNoOutputPlugin',
                stage: Compilation.PROCESS_ASSETS_STAGE_OPTIMIZE,
            }, () => {
                for (const asset of compilation.getAssets()) {
                    // If this looks like a JS file corresponding to a SCSS file...
                    if (asset.name.match(/^static\/js\/.*\.scss\.js$/)) {
                        // then don't delete it - it'll be empty anyway.
                        compilation.deleteAsset(asset.name);
                    }
                }
            });
        });
    }
}

export default defineConfig({
    plugins: [pluginSass()],
    performance: {
        chunkSplit: {
            // Other strategies require Flask to read the static files manifest to include all necessary JS chunks.
            strategy: 'all-in-one',
        },
    },
    dev: {
        // In dev mode we still need to write to disk for Flask to serve.
        writeToDisk: true,

        // Disable HMR/live reload for now - they don't work with our setup.
        hmr: false,
        liveReload: false,
    },
    tools: {
        htmlPlugin: false,
        rspack: (config) => {
            // Don't create empty .js files for CSS files.
            config.plugins.push(new SCSSNoOutputPlugin());
            // Enable JSX processing through SWC.
            config.module.rules.push({
                test: /\.jsx$/,
                use: {
                    loader: 'builtin:swc-loader',
                    options: {
                        jsc: {
                            parser: {
                                syntax: 'ecmascript',
                                jsx: true,
                            },
                        },
                    },
                },
                type: 'javascript/auto',
            });
            return config;
        },
    },
    source: {
        entry: {
            "main.js": './js/main.js',
            "line_up.js": './js/line-up.js',
            "schedule.js": './js/schedule.js',
            "volunteer_schedule.js": './js/volunteer-schedule.js',
            "event_tickets.js": './js/event-tickets.js',
            "arrivals.js": './js/arrivals.js',

            "admin.scss": './css/admin.scss',
            "arrivals.scss": './css/arrivals.scss',
            "invoice.scss": './css/invoice.scss',
            "main.scss": './css/main.scss',
            "receipt.scss": './css/receipt.scss',
            "schedule.scss": './css/schedule.scss',
            "volunteer_schedule.scss": './css/volunteer_schedule.scss',
            "flask-admin.scss": './css/flask-admin.scss',
        },
    },
    output: {
        filenameHash: false, // flask will do this for us
        manifest: './staticmanifest.json',
        copy: [
            { from: './manifest.json', to: 'static' },
            { from: './images', to: 'static/images' },
            {
                context: './node_modules/@primer/octicons/build/svg',
                from: '*.svg',
                to: 'static/icons'
            },
            {
                from: './static/**/*',
                to: '',
                globOptions: {
                    // Don't copy things we're going to output ourselves.
                    ignore: [
                        '**/fonts/**',
                        '**/flask-admin.css',
                    ],
                },
            },
        ],
        filename: {
            js: (pathData) => {
                // Don't use .js.js filenames.
                if (pathData.chunk.name.endsWith('.js')) {
                    return pathData.chunk.name;
                }
                return '[name].js';
            },
            css: (pathData) => {
                // Don't use .scss.css filenames.
                if (pathData.chunk.name.endsWith('.scss')) {
                    return pathData.chunk.name.replace('.scss', '.css');
                }
                return '[name].css';
            }
        },
        distPath: {
            html: '', // don't output HTML
            font: 'static/fonts', // use font*s* directory, rather than 'font'
            image: 'static/images', // use image*s* directory, rather than 'image'
        },
    }
});