# Dockerfile for CLARK metagenome processing
FROM ubuntu:16.04

MAINTAINER Dr. Adam G. Koziol <adam.koziol@inspection.gc.ca>

ENV DEBIAN_FRONTEND noninteractive

#COPY sources.list /etc/apt/sources.list

# Install packages
RUN apt-get update -y -qq && apt-get install -y --force-yes \
	build-essential \
	git \
	python-dev \
	python-pip \
	wget \
	zlib1g-dev && \
	apt-get clean  && \
    	rm -rf /var/lib/apt/lists/*

# Install seqtk
RUN git clone https://github.com/lh3/seqtk.git
RUN cd /seqtk && make
ENV PATH /seqtk:$PATH

# Install the pipeline
RUN git clone https://github.com/adamkoziol/metagenomeFilter.git --recursive
RUN cd metagenomeFilter && python setup.py install
ENV PATH /metagenomeFilter:$PATH

RUN wget http://clark.cs.ucr.edu/Download/CLARKV1.2.3.tar.gz
RUN tar -xvf CLARKV1.2.3.tar.gz
RUN cd /CLARKSCV1.2.3 && ./install.sh
