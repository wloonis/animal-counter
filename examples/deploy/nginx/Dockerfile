FROM nginx:1.25.3-alpine
#RUN rm /etc/nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY ./nginx/nginx.conf /etc/nginx/nginx.conf
#COPY ./nginx/default /etc/nginx/sites-available/default

# Expose the port for access
#EXPOSE 80/tcp

# Run the Nginx server
#CMD ["/usr/sbin/nginx", "-g", "daemon off;"]