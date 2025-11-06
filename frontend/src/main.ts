import { createApp } from "vue";
import ElementPlus from "element-plus";
import * as ElementPlusIconsVue from "@element-plus/icons-vue";

import App from "./App.vue";
import router from "./router";

import "element-plus/dist/index.css";
import "./style.css";

const app = createApp(App);

Object.entries(ElementPlusIconsVue).forEach(([name, component]) => {
  app.component(name, component);
});

app.use(router);
app.use(ElementPlus);
app.mount("#app");
