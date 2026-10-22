# Feature C spike: MediaPipe on my laptop

- Python version: 3.13
- MediaPipe version: 1.1.1 (old mp.solutions is gone, so I used the new FaceDetector with the blaze_face_short_range model)
- Did pip install work? Yes

## Results (my own photos only)
| Photo | Faces found | Confidence | Time (average of 5) |

| Clear, facing camera | 1 | 0.96 | 0.005 s |(Clear photos worked fine).
| Dark, night, face small | 2 | 0.81 and 0.52 | 0.005 s | (Need to check why its shows two faces).
| Wall, no face | 0 | none | 0.005 s |(No face Deteced which worked so well).

## What I learned
- It runs on the CPU in about 5 ms, so speed is not a problem.
- A clear face is found with high confidence.
- A wall gives no false detection.
- In the dark photo it found a second "face" with low confidence (0.52). There was only one person in the photo, so this looks like a false detection. We should use a stricter confidence limit (for example 0.7) and never trust a low-confidence result.
- This spike only finds a face. It does NOT read any symtoms, emotion or health sign.

## Problems or worries
- The model file (about 230 KB) is a separate download and must not be committed.
- MediaPipe prints many harmless INFO and WARNING lines.
- Real tests with other people's faces must wait for the lecturers' answer on Question 3 and ethics approval.

## Safety check
- No photos or model files were saved or committed: yes
- Used only our own photo due to the NEW ZEALAND PRIVACY ACT 2020
- After getting the consent we will use some other photos too. 