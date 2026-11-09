import type { Config } from 'tailwindcss';
const config: Config = { content: ['./src/**/*.{ts,tsx}'], theme: { extend: { colors: { ink:'#0b1119', panel:'#111a24', line:'#233140', muted:'#8fa0b2', blue:'#69aef5' } } }, plugins: [] };
export default config;
