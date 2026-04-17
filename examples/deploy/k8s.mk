.PHONY: load_k3s_countingapp
load_k3s_countingapp:
	kubectl apply -f k3s_conf/app-ns.yaml
	kubectl apply -f k3s_conf/countingapp-svc.yaml
	kubectl apply -f k3s_conf/countingapp-rs.yaml
	kubectl apply -f k3s_conf/redis-svc.yaml
	kubectl apply -f k3s_conf/redis-rs.yaml

.PHONY: load_k3s_filebrowser
load_k3s_filebrowser:
	kubectl apply -f k3s_conf/filebrowser-cmap.yaml
	envsubst < ./k3s_conf/filebrowser-dep.yaml | kubectl apply -f -
	kubectl apply -f k3s_conf/filebrowser-svc.yaml

.PHONY: load_k3s_nginx
load_k3s_nginx:
	kubectl apply -f k3s_conf/nginx-rs.yaml
	kubectl apply -f k3s_conf/nginx-svc.yaml

.PHONY: load_k3s_all
load_k3s_all:
	kubectl apply -f k3s_conf/app-ns.yaml
	envsubst < ./k3s_conf/deletevideo-job.yaml | kubectl apply -f -
	envsubst < ./k3s_conf/countingapp-rs.yaml | kubectl apply -f -
	kubectl apply -f k3s_conf/countingapp-svc.yaml
	kubectl apply -f k3s_conf/redis-rs.yaml
	kubectl apply -f k3s_conf/redis-svc.yaml
	kubectl apply -f k3s_conf/filebrowser-cmap.yaml
	envsubst < ./k3s_conf/filebrowser-dep.yaml | kubectl apply -f -
	kubectl apply -f k3s_conf/filebrowser-svc.yaml
	kubectl apply -f k3s_conf/nginx-rs.yaml
	kubectl apply -f k3s_conf/nginx-svc.yaml
