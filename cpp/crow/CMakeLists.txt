cmake_minimum_required(VERSION 3.25)

project(mcp-crow LANGUAGES CXX)

find_package(Crow REQUIRED)
if(NOT TARGET asio::asio)
  message(FATAL_ERROR "asio not found")
endif()

add_executable(mcp mcp.cc)
target_link_libraries(mcp PRIVATE Crow::Crow asio::asio)
