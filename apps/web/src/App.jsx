import { useEffect, useState } from 'react'
import {
  Activity, Bot, BrainCircuit, ChevronDown, CircleHelp, ClipboardList,
  FileText, HeartPulse, LayoutDashboard, Menu, MessageSquare, Plus,
  ShieldCheck, Users, Wifi, WifiOff
} from 'lucide-react'

const agents = [
  ['Supervisor Agent', 'ចាត់ចែងការងារ និងសម្របសម្រួល', 'SA', 'bg-violet-500/15 text-violet-300'],
  ['MNCH Specialist', 'សុខភាពមាតា និងទារក', 'MN', 'bg-pink-500/15 text-pink-300'],
  ['Health Data Analyst', 'វិភាគទិន្នន័យ និងសូចនាករ', 'DA', 'bg-cyan-500/15 text-cyan-300'],
  ['Report Writer', 'រៀបចំរបាយការណ៍', 'RW', 'bg-amber-500/15 text-amber-300'],
]
const nav = [
  [LayoutDashboard, 'ទិដ្ឋភាពទូទៅ', true],
  [MessageSquare, 'ក្រុមជជែក AI', false],
  [Bot, 'គ្រប់គ្រង Agent', false],
  [ClipboardList, 'គម្រោង និងសកម្មភាព', false],
  [FileText, 'ឯកសារ និងរបាយការណ៍', false],
  [Users, 'អ្នកប្រើប្រាស់', false],
]

export default function App() {
  const [apiStatus, setApiStatus] = useState('checking')
  const [apiInfo, setApiInfo] = useState(null)

  useEffect(() => {
    let active = true
    fetch('/api/v1/health')
      .then(r => { if (!r.ok) throw new Error('API unavailable'); return r.json() })
      .then(data => { if (active) { setApiStatus('online'); setApiInfo(data) } })
      .catch(() => { if (active) setApiStatus('offline') })
    return () => { active = false }
  }, [])

  return (
    <div className="min-h-screen bg-[#08111f] text-slate-100 lg:flex">
      <aside className="hidden w-64 shrink-0 border-r border-white/10 bg-[#0b1626] p-5 lg:flex lg:flex-col">
        <div className="mb-10 flex items-center gap-3">
          <div className="rounded-xl bg-cyan-400/15 p-2.5 text-cyan-300"><HeartPulse size={25}/></div>
          <div><div className="font-semibold tracking-tight">Healthcare AI Desk</div><div className="text-xs text-slate-500">AI Workforce Platform</div></div>
        </div>
        <div className="mb-3 px-3 text-[11px] font-semibold uppercase tracking-[.18em] text-slate-500">Workspace</div>
        <nav className="space-y-1">
          {nav.map(([Icon, label, active]) => (
            <a key={label} href="#" onClick={e => e.preventDefault()}
              className={`flex items-center gap-3 rounded-xl px-3 py-3 text-sm ${active ? 'bg-cyan-400/10 text-cyan-200 ring-1 ring-cyan-400/20' : 'text-slate-400 hover:bg-white/5 hover:text-white'}`}>
              <Icon size={18}/>{label}
            </a>
          ))}
        </nav>
        <div className="mt-auto rounded-2xl border border-white/10 bg-white/[.03] p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-medium"><ShieldCheck size={17} className="text-emerald-300"/> Human oversight</div>
          <p className="text-xs leading-5 text-slate-500">ការងារដែលមានហានិភ័យខ្ពស់ ត្រូវការការត្រួតពិនិត្យ និងអនុម័តពីមនុស្ស។</p>
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <header className="flex h-[76px] items-center justify-between border-b border-white/10 px-5 md:px-8">
          <div className="flex items-center gap-3">
            <button className="rounded-lg p-2 text-slate-400 hover:bg-white/5 lg:hidden" aria-label="Open menu"><Menu size={20}/></button>
            <div><div className="text-sm text-slate-400">Workspace / Dashboard</div><h1 className="text-lg font-semibold">ទិដ្ឋភាពទូទៅ</h1></div>
          </div>
          <div className="flex items-center gap-3">
            <div className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs ${apiStatus === 'online' ? 'border-emerald-400/20 bg-emerald-400/10 text-emerald-300' : apiStatus === 'offline' ? 'border-rose-400/20 bg-rose-400/10 text-rose-300' : 'border-amber-400/20 bg-amber-400/10 text-amber-200'}`}>
              {apiStatus === 'online' ? <Wifi size={14}/> : <WifiOff size={14}/>} API {apiStatus}
            </div>
            <button className="flex items-center gap-2 rounded-full border border-white/10 px-3 py-2 text-sm text-slate-300">
              <span className="grid h-7 w-7 place-items-center rounded-full bg-cyan-400/15 text-xs text-cyan-200">AD</span>
              <span className="hidden sm:inline">Administrator</span><ChevronDown size={14}/>
            </button>
          </div>
        </header>

        <div className="mx-auto max-w-7xl space-y-7 p-5 md:p-8">
          <section className="relative overflow-hidden rounded-3xl border border-cyan-300/15 bg-gradient-to-br from-[#12304a] via-[#10243a] to-[#171d38] p-6 md:p-8">
            <div className="relative z-10 max-w-2xl">
              <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-cyan-200/20 bg-cyan-200/10 px-3 py-1 text-xs text-cyan-200"><BrainCircuit size={14}/> Your AI healthcare workforce</div>
              <h2 className="text-2xl font-semibold leading-tight md:text-3xl">សូមស្វាគមន៍មកកាន់ Healthcare AI Desk</h2>
              <p className="mt-3 max-w-xl text-sm leading-6 text-slate-300">គ្រប់គ្រងក្រុម AI Agents និងសម្របសម្រួលលំហូរការងារសុខាភិបាលរបស់អ្នកនៅកន្លែងតែមួយ។</p>
              <button className="mt-6 inline-flex items-center gap-2 rounded-xl bg-cyan-300 px-4 py-2.5 text-sm font-semibold text-slate-950 hover:bg-cyan-200"><Plus size={17}/> បង្កើត Agent ថ្មី</button>
            </div>
            <div className="pointer-events-none absolute -right-12 -top-20 h-80 w-80 rounded-full border border-cyan-200/10"/>
            <div className="pointer-events-none absolute -right-2 -top-10 h-60 w-60 rounded-full border border-cyan-200/10"/>
            <div className="pointer-events-none absolute right-16 top-16 hidden rounded-3xl border border-white/10 bg-white/5 p-5 backdrop-blur-sm md:block"><BrainCircuit size={70} className="text-cyan-200/70"/></div>
          </section>

          <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {[
              [Bot, 'AI Agents', '13', 'គោលដៅក្រុម Agent', 'text-violet-300'],
              [MessageSquare, 'Conversations', '0', 'ការសន្ទនាថ្មី', 'text-cyan-300'],
              [Activity, 'Active Tasks', '0', 'កំពុងដំណើរការ', 'text-emerald-300'],
              [ShieldCheck, 'Pending Approvals', '0', 'រង់ចាំការអនុម័ត', 'text-amber-300']
            ].map(([Icon, label, value, sub, color]) => (
              <div key={label} className="rounded-2xl border border-white/10 bg-[#0d1929] p-5">
                <div className="flex items-center justify-between"><span className="text-sm text-slate-400">{label}</span><Icon size={19} className={color}/></div>
                <div className="mt-4 text-3xl font-semibold">{value}</div><div className="mt-1 text-xs text-slate-500">{sub}</div>
              </div>
            ))}
          </section>

          <section className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
            <div className="rounded-2xl border border-white/10 bg-[#0d1929] p-5">
              <div className="mb-5 flex items-center justify-between">
                <div><h3 className="font-semibold">ក្រុម AI Agents</h3><p className="mt-1 text-xs text-slate-500">ឧទាហរណ៍តួនាទីសម្រាប់ Healthcare AI Desk</p></div>
                <button className="text-xs text-cyan-300">មើលទាំងអស់</button>
              </div>
              <div className="space-y-3">
                {agents.map(([name, desc, initials, style]) => (
                  <div key={name} className="flex items-center gap-3 rounded-xl border border-white/5 bg-white/[.02] p-3">
                    <div className={`grid h-10 w-10 place-items-center rounded-xl text-xs font-bold ${style}`}>{initials}</div>
                    <div className="min-w-0 flex-1"><div className="text-sm font-medium">{name}</div><div className="mt-1 truncate text-xs text-slate-500">{desc}</div></div>
                    <span className="rounded-full bg-slate-700/50 px-2.5 py-1 text-[10px] text-slate-400">Planned</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-[#0d1929] p-5">
              <div className="mb-5 flex items-center gap-2"><Activity size={18} className="text-cyan-300"/><h3 className="font-semibold">System status</h3></div>
              <div className="space-y-4">
                {['Frontend', 'Backend API', 'MySQL Database', 'Redis Cache'].map((name, i) => (
                  <div key={name} className="flex items-center justify-between border-b border-white/5 pb-3 last:border-0">
                    <span className="text-sm text-slate-300">{name}</span>
                    <span className={`text-xs ${i === 0 || apiStatus === 'online' ? 'text-emerald-300' : 'text-amber-300'}`}>{i === 0 ? 'Loaded' : i === 1 ? apiStatus : 'Verify readiness'}</span>
                  </div>
                ))}
              </div>
              <div className="mt-5 rounded-xl bg-slate-800/60 p-3 text-xs leading-5 text-slate-400">{apiInfo ? `API service: ${apiInfo.service}` : 'Database និង Redis ត្រូវពិនិត្យតាម readiness endpoint។'}</div>
              <div className="mt-4 flex items-start gap-2 text-xs leading-5 text-slate-500"><CircleHelp size={15} className="mt-0.5 shrink-0"/> M1.1 starter interface. Agent counts and task metrics are illustrative, not live database records.</div>
            </div>
          </section>

          <footer className="flex flex-col gap-2 border-t border-white/10 pt-5 text-xs text-slate-600 sm:flex-row sm:justify-between">
            <span>Healthcare AI Desk · M1.1 Development Foundation</span><span>Local-first · Human oversight · Privacy by design</span>
          </footer>
        </div>
      </main>
    </div>
  )
}
