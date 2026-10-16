import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { ApiClient } from './api/client'
import { config } from './config'
import './styles.css'

const root = document.getElementById('root')
if (!root) throw new Error('missing #root')

createRoot(root).render(
  <StrictMode>
    <App api={new ApiClient(config.apiBase)} />
  </StrictMode>,
)
