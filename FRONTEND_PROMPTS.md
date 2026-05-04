# Multimodal Virtual Clinic — Frontend AI Prompts

> **Note to Examiner:** This document outlines the key AI prompts and instructions used to architect, scaffold, and implement the Flutter frontend. 

By providing specific, architecture-driven prompts to the AI, we ensured the codebase remained clean, scalable, and followed the **Provider** state management pattern.

---

## 1. Project Initialization & Architecture

**Prompt 1: Scaffolding the Architecture**
> "I am building a Multimodal Virtual Clinic frontend in Flutter. Create a highly scalable folder structure inside the `lib/` directory. Include folders for `core` (constants, themes), `models` (data shapes), `providers` (state management), `services` (API and hardware communication), and `screens` (UI views). Explain what each folder is responsible for."

**Prompt 2: UI Theming & Constants**
> "Create a file called `app_colors.dart` inside `lib/core/constants/`. Define a modern, medical-themed color palette using gradients and glassmorphism. Include specific hexadecimal colors for 'primary', 'accent', 'background', and specific sensor colors (EEG, BP, Pulse, Emotion)."

**Prompt 3: API Configuration**
> "Create an `api_constants.dart` file that holds a centralized base URL (e.g., `http://192.168.X.X:8000`). This will ensure that if my FastAPI server IP changes, I only have to update it in one place."

---

## 2. Authentication & Login

**Prompt 4: Login Screen UI**
> "Generate a `LoginScreen` widget in Flutter. Use the gradients from my `AppColors` file for the background. Create a frosted-glass (glassmorphic) container using `BackdropFilter` and `BoxDecoration`. Inside the container, place two `TextFields` for email and password, and an 'Enter Clinic' button."

**Prompt 5: AuthProvider State Management**
> "Write an `AuthProvider` class using the `provider` package. Add a `login` method that uses the Flutter `http` package to send a JSON POST request with the email and password to my FastAPI backend. If the response is 200 OK, parse the `UserModel` and the JWT token, save them in memory, and use `notifyListeners()` to update the UI."

---

## 3. Hardware & Camera Services

**Prompt 6: Background Camera Capture**
> "Write a `CameraService` class in Flutter using the official `camera` package. I need a method that initializes the *front* camera silently. Then, write a method that captures a picture without showing a shutter flash, and immediately converts the image file bytes into a `Base64` encoded string."

**Prompt 7: Sending Images via API**
> "In my `ApiService` class, write a method called `sendEmotionFrame`. It should take the Base64 image string, the current `sessionId`, and the `userId`. It must send this as a JSON POST request to `/sensors/emotion`. Make sure to attach the JWT token in the `Authorization: Bearer` header."

---

## 4. Session & Questionnaire Flow

**Prompt 8: Camera Permission Popup**
> "In my `session_screen.dart`, I have a 'Start Session' button. Instead of starting the session immediately, change the `onPressed` logic to show a modern `AlertDialog` popup. The popup should ask for 'Camera Permission' and explain that we will record their face. Give them a 'Cancel' button and an 'I Agree' button. Only trigger the API call if they click 'I Agree'."

**Prompt 9: The Background Timer**
> "In my `SessionProvider`, I need to capture the user's face while they answer the questionnaire. When the session starts, initialize a `Timer.periodic` that triggers every 5 seconds. Inside the timer, call the `CameraService` to snap a picture, and pass the Base64 string to `ApiService.sendEmotionFrame`. Ensure the timer is cancelled when the session ends."

**Prompt 10: Questionnaire UI**
> "Create a `QuestionnaireScreen` in Flutter. The backend sends a list of questions grouped into stages. Build a UI that displays the current question using a large, readable font. Below the question, add a 0-to-4 slider (from 'Not at all' to 'Severely') for the user to answer. Add a 'Next' button that saves the answer and moves to the next question using a `PageView` controller."

---

## 5. Results & Dashboard

**Prompt 11: Machine Learning Results Screen**
> "Create a `ResultsScreen` widget. It should call `ApiService.getResult(sessionId)` when it loads. Display the final ML prediction (e.g., 'Normal', 'See Psychologist') prominently at the top. Below that, display a breakdown of the 5 questionnaire component scores (Emotional, Functional, Context, etc.) using linear progress bars."

**Prompt 12: Error Handling & UX**
> "Add error handling to my `ApiService` calls. If the server is down or returns a 500 error, catch the exception and use a `ScaffoldMessenger.showSnackBar` to display a user-friendly error message floating at the bottom of the screen with a red background, rather than crashing the app."
