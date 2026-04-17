from ultralytics import YOLO

model = YOLO("yolov8n.pt")  # modèle pré-entraîné

results = model("./model/frame_00013.jpg")

results[0].save()  # image avec bounding boxes
