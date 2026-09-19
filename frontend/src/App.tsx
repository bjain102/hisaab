import { Route, Routes } from 'react-router'
import AppShell from './shell/AppShell'
import Dashboard from './pages/Dashboard'
import Transactions from './pages/Transactions'
import Import from './pages/Import'
import Rewards from './pages/Rewards'
import Kit from './pages/Kit'

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Dashboard />} />
        <Route path="transactions" element={<Transactions />} />
        <Route path="import" element={<Import />} />
        <Route path="rewards" element={<Rewards />} />
        <Route path="kit" element={<Kit />} />
      </Route>
    </Routes>
  )
}
