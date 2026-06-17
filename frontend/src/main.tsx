import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import "./index.css";
import Landing from "./pages/Landing";
import Pad from "./pages/Pad";

const router = createBrowserRouter([
  { path: "/", element: <Landing /> },
  { path: "/:slug", element: <Pad /> },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
