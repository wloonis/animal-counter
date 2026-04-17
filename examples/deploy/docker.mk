.PHONY: build_redis
build_redis:
	docker build --tag=redis:local -f redis/Dockerfile .

.PHONY: build_countingapp
build_countingapp:
	docker build --network host --tag=countingapp:local -f app/Dockerfile .

.PHONY: build_nginx
build_nginx:
	docker build --network host --tag=nginx:local -f nginx/Dockerfile .

.PHONY: run_redis
run_redis:
	docker run --detach --publish=6379:6379 --name=redis redis

.PHONY: run_countingapp
run_countingapp:
	docker run -it --gpus all --rm --runtime nvidia --network host -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix:rw -v /media/thomasai/data/repository/git/jetson-yolov7-k3s-counting/app:/app -v /dev/video0:/dev/video0 -v /media/thomasai/data/files:/data --publish=31501:31501 --name=countingapp countingapp:local

.PHONY: pull_filebrowser
pull_filebrowser:
	docker pull filebrowser/filebrowser

.PHONY: run_filebrowser
run_filebrowser:
	docker run -v /home/odoo:/srv -v ./filebrowser/filebrowser.db:/database.db -v ./filebrowser/docker_config.json:/.filebrowser.json -u $(id -u):$(id -g) -p 8089:80 filebrowser/filebrowser
