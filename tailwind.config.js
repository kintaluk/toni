/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './static/**/*.html',
    './static/**/*.js',
    './src/**/*.py'
  ],
  safelist: [
    // Dynamic service chip states
    'border-lime',
    'bg-lime/25',
    'text-ink',
    'font-semibold',
    'border-ink/20',
    'bg-bone',
    'text-ink/80',
    'text-ink/75',
    'text-ink-muted',
    'text-ink-subtle',
    // Dynamic microphone voice states
    'border-lime/60',
    'bg-lime/10',
    'ring-2',
    'ring-lime',
    'animate-pulse',
    'border-ink/40',
    'active:scale-95',
    'shadow-2xs',
    // Chat message animation & layout
    'chat-message-anim',
    'justify-end',
    'justify-start',
    'items-start',
    'pl-10',
    'my-3',
    // Dynamic badges & role chips
    'bg-lime',
    'bg-lime/15',
    'bg-lime/20',
    'border-lime/40',
    'border-t-4',
    'border-t-lime',
    'rounded-[2px]',
    'rounded-[3px]',
    'rounded-[4px]',
    'rounded-[6px]',
    'rounded-[8px]',
    'rounded-tr-xs',
    'shadow-xs',
    'shadow-sm',
    'shadow-md',
    'active:scale-98',
    'bg-bone-dark',
    'bg-white/70',
    'bg-white/85',
    'bg-white/90',
    'backdrop-blur-xs',
    'bg-black/40',
    'bg-black/70'
  ],
  theme: {
    extend: {
      colors: {
        'bone': '#F6F4EE',
        'bone-card': '#FAF8F3',
        'bone-surface': '#FFFFFF',
        'bone-dark': '#ECE8DE',
        'ink': '#1A1D20',
        'ink-muted': '#555C63',
        'ink-subtle': '#8A929A',
        'ink-border': 'rgba(26, 29, 32, 0.12)',
        'ink-border-strong': 'rgba(26, 29, 32, 0.28)',
        'lime': '#C2E85E',
        'lime-hover': '#B6DC51',
        'lime-dark': '#8DAF29'
      },
      fontFamily: {
        serif: ['Newsreader', 'Georgia', 'serif'],
        sans: ['"Plus Jakarta Sans"', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
      },
      scale: {
        '98': '0.98',
      },
      borderRadius: {
        'xs': '2px',
      },
      backdropBlur: {
        'xs': '2px',
      },
      boxShadow: {
        '2xs': '0 1px 2px 0 rgba(0, 0, 0, 0.03)',
        'xs': '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
      },
      spacing: {
        '0.2': '0.05rem',
      }
    }
  },
  plugins: []
};
