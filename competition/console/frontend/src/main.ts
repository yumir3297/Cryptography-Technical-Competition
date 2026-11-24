import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import '../../../web/static/prts/prts-design.css'
import '../../../web/static/shared/ak-theme.css'
import '../../../web/static/observe/observe-backdrop.js'

import App from './App.vue'
import './style.css'
import { installFlushHooks } from './trace'

// Element Plus 的暗色变量挂在 .dark 上；PRTS 侧同时用 data-theme。
document.documentElement.classList.add('dark')
installFlushHooks()
createApp(App).use(ElementPlus, { locale: zhCn }).mount('#app')
