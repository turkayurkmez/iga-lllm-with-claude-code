import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router'
import './index.css'
import App from './App.tsx'
import Chat from './Chat.tsx'

// /chat backend'e proxy'lenir (vite.config.ts); sohbet sayfası bu yüzden /sohbet'tedir.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/sohbet" element={<Chat />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
