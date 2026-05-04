# Frontend Guide — Multimodal Virtual Clinic (Flutter)

This guide is written in **easy English** to help you prepare for your Final Year Project (FYP) demo and viva. It explains how your Flutter frontend works, exactly which files contain the logic, the techniques used, and how to answer common viva questions.

---

## 1. Project Structure & Exact Files (Where is everything?)

To keep the code clean and easy to maintain, the Flutter code inside the `frontend/lib/` folder is divided into specific folders. If the examiner asks to see a specific feature, here is exactly where to open the code:

### ⚙️ `core/` (Global Constants)
*   **`core/constants/api_constants.dart`**: This is where we store the FastAPI server's IP address (e.g., `192.168.x.x:8000`). If we change networks, this is the ONLY file we edit.
*   **`core/constants/app_colors.dart`**: Contains all the exact HEX codes for our modern UI gradients and glassmorphism elements.

### 📦 `models/` (Data Structures)
*   **`models/user_model.dart`**: Defines the `UserModel` class. When the backend sends user info, we convert the JSON into this Dart object.
*   **`models/session_model.dart`**: Defines the `SessionModel` class, which holds active session tracking data.

### 🧠 `providers/` (State Management)
*   **`providers/auth_provider.dart`**: Handles User Login state. It holds the JWT token and the `UserModel` in memory. If the token expires, this file logs the user out.
*   **`providers/session_provider.dart`**: The "brain" of the session. It manages the background camera timer, tracks which stage of the questionnaire the user is on, and holds the current `sessionId`.

### 🔌 `services/` (Background Workers)
*   **`services/api_service.dart`**: The bridge to FastAPI. This file contains all the standard HTTP `POST` and `GET` requests (using the `http` package). It automatically attaches the JWT token to the headers.
*   **`services/camera_service.dart`**: Controls the front camera. It takes a picture silently, converts it into a `Base64` string, and passes it to the `api_service.dart` to send to the backend.

### 📱 `screens/` (The UI Views)
*   **`screens/auth/login_screen.dart`**: The login page.
*   **`screens/home/home_screen.dart`**: The main dashboard.
*   **`screens/session/session_screen.dart`**: The screen where you click "Start Session". **This is where the glassmorphic Camera Permission popup logic is written.**
*   **`screens/session/questionnaire_screen.dart`**: Displays the active questionnaire and handles stage progression.
*   **`screens/results/results_screen.dart`**: Fetches and displays the final Machine Learning risk breakdown.

---

## 2. Key Techniques Used & Their Logic

### A. State Management (Provider)
**Where is it used?** `providers/auth_provider.dart` and `providers/session_provider.dart`
**What it is:** We use the `provider` package to manage state across the entire app. 
**Why we used it:** Imagine you log in on the Login Screen. You get a `user_id` and a `token`. Without Provider, you would have to pass these variables manually from screen to screen. With Provider, the data is saved in a central "vault" at the top of the app. Any screen can just call `context.read<AuthProvider>().token` to get the data instantly, without passing parameters.

### B. API Communication (HTTP & JSON)
**Where is it used?** `services/api_service.dart`
**What it is:** The frontend talks to the Python backend using REST APIs.
**How it works:** 
- We use the Flutter `http` package.
- **Security:** We use **JWT (JSON Web Tokens)**. When the user logs in, the backend gives a Token. For every future request (like submitting a questionnaire), `api_service.dart` automatically injects this token into the `Authorization: Bearer <token>` header. If the token is missing, the backend blocks the request.

### C. Background Camera Timer
**Where is it used?** `providers/session_provider.dart` and `services/camera_service.dart`
**What it is:** Taking pictures of the user's face without making them click a button.
**How it works:** In `SessionProvider`, when the user starts the test, we start a Dart `Timer.periodic`. Every 5 seconds, it triggers the `CameraService` to snap a picture. 
**Important Technique:** The picture is converted to a `base64` string (raw text) because sending a Base64 string inside standard JSON is much faster and more reliable than uploading a heavy physical file over a REST API.

### D. Modern UI/UX (Glassmorphism & Gradients)
**Where is it used?** Inside almost all `screens/` files.
**How we did it:** 
- **Gradients:** We used `BoxDecoration` with `LinearGradient` instead of flat colors to make the background look dynamic.
- **Glassmorphism:** We used semi-transparent containers with blur effects (`BackdropFilter`) to make cards look like frosted glass.
- **Feedback:** We used `ScaffoldMessenger` (SnackBars) to show popup notifications (like "Login failed") floating at the bottom of the screen.

---

## 3. How the App Flows (End-to-End Demo Guide)

When showing the app to the external examiner, walk them through this exact flow:

1.  **Login (`login_screen.dart`):** Explain that registration is disabled for clinical security. Users are pre-registered in the database. When you log in, Flutter receives a JWT Token.
2.  **Start Session & Consent (`session_screen.dart`):** When you click "Start Session", a glassmorphic dialog pops up asking for Camera Permission. Once agreed, Flutter hits the `/session/start` backend API. Tell the examiner: *"This triggers a background thread on the FastAPI server that continuously collects 30-second windows of EEG and PPG hardware data."*
3.  **The Questionnaire (`questionnaire_screen.dart`):** Show the questions. The questionnaire is divided into sequential stages. Mention that while you are answering, the front camera (`camera_service.dart`) is secretly taking a picture every 5 seconds to track facial distress.
4.  **End Session (`session_screen.dart`):** When you finish, the app hits the `/session/end` API. The backend stops the hardware thread, aggregates all the 30-second windows, and feeds the 16-element feature vector to our Machine Learning models.
5.  **Results Screen (`results_screen.dart`):** The app fetches the final ML prediction and displays the clinical recommendation clearly.

---

## 4. Viva Preparation: Common Questions & Easy Answers

**Q1: Why did you choose Flutter for the frontend?**
*Answer:* "Flutter is a cross-platform framework by Google. It allowed us to build the app for both Android and iOS from a single codebase using the Dart language. It also provides rich UI widgets which helped us create a modern, premium look for the clinic."

**Q2: How is the app communicating with the Python backend?**
*Answer:* "We use RESTful APIs built with the **FastAPI** framework in Python. The Flutter frontend uses the standard `http` package (inside our `api_service.dart` file) to send POST and GET requests containing JSON data to our FastAPI endpoints. We also use JWT (JSON Web Tokens) for secure communication."

**Q3: How does the app take pictures without freezing the screen?**
*Answer:* "We use Flutter's asynchronous programming (`async` and `await`). Taking a picture and sending it over the network happens on a background thread (event loop) so the main UI thread doesn't freeze, keeping the questionnaire smooth."

**Q4: What happens if the backend server's IP address changes?**
*Answer:* "We stored the server IP in a single file called `api_constants.dart`. If we change networks, we only have to change the IP address in that one file, and the whole app updates instantly."

**Q5: How do you handle user login data?**
*Answer:* "We use the `Provider` architecture (`auth_provider.dart`). It holds the user's ID, Role, and JWT token in memory globally. If the token expires or the user logs out, the provider clears the data and kicks the user back to the login screen."

**Q6: Why convert the camera image to Base64?**
*Answer:* "Sending a raw image file requires 'multipart form data' which is heavy and complex. Converting the image to a Base64 text string allows us to easily pack it inside a standard JSON payload along with the `session_id` and `user_id`."

**Q7: Why do we process EEG/PPG in 30-second windows?**
*Answer:* "Instead of flooding our database with hundreds of raw sensor readings per second, our FastAPI backend aggregates the data every 30 seconds into a `WindowAnalysis` table. This extracts the exact frequency bands (Alpha, Beta, Theta) needed for our Machine Learning model while keeping the system highly efficient."

**Q8: How did you implement user consent for the camera?**
*Answer:* "Before the session starts in `session_screen.dart`, we display an interactive Dialog popup. We do not start the background camera timers or hit the backend API until the user explicitly taps 'I Agree', ensuring ethical clinical data collection."

---
*Good luck with your Demo and Viva! Speak confidently—you know exactly where every file is and how this complex AI pipeline works.*
