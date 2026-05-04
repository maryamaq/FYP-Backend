# Frontend Guide — Multimodal Virtual Clinic (Flutter)

This guide is written in **easy English** to help you prepare for your Final Year Project (FYP) demo and viva. It explains how your Flutter frontend works, the techniques used, and how to answer common viva questions.

---

## 1. Project Structure (How the Code is Organized)

To keep the code clean and easy to maintain, the Flutter code inside the `lib/` folder is divided into specific folders:

*   **`core/`**: Holds things that are used everywhere, like colors (`AppColors`), text styles, and the API base URL (`api_constants.dart`).
*   **`models/`**: Defines the shapes of data (e.g., `UserModel`, `SessionModel`). This maps exactly to the FastAPI backend models.
*   **`providers/`**: Handles the **State Management** (storing data while the app is running).
*   **`services/`**: Handles all the hard work in the background, like making HTTP requests to the backend API (`api_service.dart`) or controlling the camera (`camera_service.dart`).
*   **`screens/`**: The actual UI pages the user sees (Login Screen, Session Screen, Results Screen).

---

## 2. Key Techniques Used

### A. State Management (Provider)
**What it is:** We use the `provider` package to manage state. 
**Why we used it:** Imagine you log in on the Login Screen. You get a `user_id` and a `token`. Without Provider, you would have to pass these variables manually to the Home Screen, then to the Session Screen, then to the Results Screen. 
With Provider (`AuthProvider` and `SessionProvider`), the data is saved in a central "vault". Any screen can just say `context.read<AuthProvider>().token` to get the data instantly.

### B. API Communication (HTTP & JSON)
**What it is:** The frontend talks to the Python backend using REST APIs.
**How it works:** 
- We use the `http` package.
- Every time we need data, we send a JSON request. 
- **Security:** We use **JWT (JSON Web Tokens)**. When the user logs in, the backend gives a Token. For every future request (like submitting a questionnaire), the frontend automatically attaches this token in the headers (`Authorization: Bearer <token>`). If the token is missing, the backend blocks the request.

### C. Background Camera Timer
**What it is:** Taking pictures of the user's face without making them click a button.
**How it works:** In `SessionProvider`, when the user starts the test, we start a `Timer.periodic`. Every 5 seconds, it triggers the `CameraService` to snap a picture. 
**Important Technique:** The picture is converted to a `base64` string (raw text) because it is much faster and easier to send over a REST API via JSON than uploading a physical file.

### D. Modern UI/UX (Glassmorphism & Gradients)
**What it is:** Making the app look like a premium, modern clinic.
**How we did it:** 
- **Gradients:** We used `BoxDecoration` with `LinearGradient` instead of flat colors to make the background look alive.
- **Glassmorphism:** We used semi-transparent containers with blur effects (`BackdropFilter`) to make cards look like frosted glass.
- **Feedback:** We used `ScaffoldMessenger` (SnackBars) to show error messages (like "Login failed") floating on the screen instead of annoying popup alerts.

---

## 3. How the App Flows (End-to-End Demo Guide)

When showing the app to the external examiner, walk them through this exact flow:

1.  **Login:** Explain that registration is disabled for clinical security. Users are pre-registered in the database. When you log in, Flutter gets a JWT Token.
2.  **Start Session:** When you click "Start", Flutter hits the `/session/.../start_with_muse` backend API. Tell the examiner: *"This secretly starts the Muse EEG headset and grabs the baseline Blood Pressure in the background."*
3.  **The Questionnaire:** Show the questions. Mention that while you are answering, the front camera is secretly taking a picture every 5 seconds.
4.  **End Session:** When you finish, the app hits the `end_with_muse` API to capture the final Blood Pressure, stop the EEG, and calculate the Machine Learning result.
5.  **Results Screen:** The app fetches the final ML prediction and displays the breakdown clearly.

---

## 4. Viva Preparation: Common Questions & Easy Answers

**Q1: Why did you choose Flutter for the frontend?**
*Answer:* "Flutter is a cross-platform framework by Google. It allowed us to build the app for both Android and iOS from a single codebase. It also provides rich UI widgets which helped us create a modern, premium look for the clinic."

**Q2: How is the app communicating with the Python backend?**
*Answer:* "We use RESTful APIs. The Flutter app uses the HTTP package to send HTTP POST and GET requests containing JSON data. We use JWT (JSON Web Tokens) for secure communication."

**Q3: How does the app take pictures without freezing the screen?**
*Answer:* "We use Flutter's asynchronous programming (`async` and `await`). Taking a picture and sending it over the network happens on a background thread so the main UI thread doesn't freeze, keeping the questionnaire smooth."

**Q4: What happens if the backend server's IP address changes?**
*Answer:* "We stored the server IP in a single file called `api_constants.dart`. If we change networks, we only have to change the IP address in that one file, and the whole app updates."

**Q5: How do you handle user login data?**
*Answer:* "We use the `Provider` architecture. The `AuthProvider` holds the user's ID, Role, and JWT token in memory. If the token expires or the user logs out, the provider clears the data and kicks the user back to the login screen."

**Q6: Why convert the camera image to Base64?**
*Answer:* "Sending a raw image file requires 'multipart form data' which is heavy and complex. Converting the image to a Base64 text string allows us to easily pack it inside a standard JSON payload along with the `session_id` and `user_id`."

---
*Good luck with your Demo and Viva! Speak confidently—you have a fully functioning, complex AI pipeline supporting this app.*
