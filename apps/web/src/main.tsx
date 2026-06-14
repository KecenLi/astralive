import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { initUiScale } from "./lib/uiScale";
import "./styles/global.css";

initUiScale();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

