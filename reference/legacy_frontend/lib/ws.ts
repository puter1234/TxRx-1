import { useApp } from './store'

let ws: WebSocket | null = null
let retry: number | undefined

export function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const url = proto + '://' + location.host + '/ws'
  try {
    ws = new WebSocket(url)
  } catch {
    retry = window.setTimeout(connectWS, 2000)
    return
  }
  ws.onopen = () => useApp.getState().setConnected(true)
  ws.onmessage = (e) => {
    let msg: any
    try {
      msg = JSON.parse(e.data)
    } catch {
      return
    }
    const st = useApp.getState()
    if (msg.type === 'state') st.setServer(msg.state)
    else if (msg.type === 'log') st.pushLog(msg.item)
    else if (msg.type === 'logs') st.setLogs(msg.items)
    else if (msg.type === 'brands') st.setBrands(msg.brands)
  }
  ws.onclose = () => {
    useApp.getState().setConnected(false)
    window.clearTimeout(retry)
    retry = window.setTimeout(connectWS, 2000)
  }
  ws.onerror = () => {
    if (ws) ws.close()
  }
}
