import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: process.env.NODE_ENV === "production" ? "/Creamy-Smart_Money_Track_Agent/" : "/",
  server: {
    port: 5173,
    host: true,
  },
})
