from ultralytics import YOLO

# Load a YOLO26n PyTorch model
model = YOLO("yolo26s.pt")

# Export the model to TensorRT
model.export(format="engine")  # creates 'yolo26n.engine'

# Load the exported TensorRT model
trt_model = YOLO("yolo26s.engine")

# Run inference
results = trt_model("/app/model/frame_00013.jpg")