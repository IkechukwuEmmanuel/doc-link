import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import "./index.css";
import { AuthProvider } from "./auth";
import AuthPage from "./pages/AuthPage";
import Landing from "./pages/Landing";
import Pad from "./pages/Pad";

const router = createBrowserRouter([
  { path: "/", element: <Landing /> },
  { path: "/login", element: <AuthPage mode="login" /> },
  { path: "/signup", element: <AuthPage mode="signup" /> },
  { path: "/:slug", element: <Pad /> },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  </React.StrictMode>
);
